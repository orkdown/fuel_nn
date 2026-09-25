// State
let allStations = [];
let filteredStations = [];
let currentFuel = 'all';
let currentBrand = 'all';
let onlyAvailable = false;
let searchQuery = '';
let userCoords = null;
let currentView = 'map'; // 'map' or 'list'

let map = null;
let markersLayer = null;
let userMarker = null;

const NN_CENTER = [56.3269, 44.0059];

// Brand styling map
const BRAND_META = {
  'Лукойл': { code: 'Л', cls: 'marker-lukoil', cardCls: 'brand-lukoil' },
  'Татнефть': { code: 'Т', cls: 'marker-tatneft', cardCls: 'brand-tatneft' },
  'Газпромнефть': { code: 'Г', cls: 'marker-gpn', cardCls: 'brand-gpn' },
  'ОПТИ': { code: 'О', cls: 'marker-opti', cardCls: 'brand-other' },
  'default': { code: '⛽', cls: 'marker-other', cardCls: 'brand-other' }
};

function getBrandMeta(brand) {
  const b = brand || '';
  if (b.includes('Лукойл')) return BRAND_META['Лукойл'];
  if (b.includes('Татнефть')) return BRAND_META['Татнефть'];
  if (b.includes('Газпром')) return BRAND_META['Газпромнефть'];
  if (b.includes('ОПТИ')) return BRAND_META['ОПТИ'];
  return BRAND_META['default'];
}

// Distance calculation (Haversine formula in km)
function calcDistance(lat1, lon1, lat2, lon2) {
  const R = 6371; // Earth's radius in km
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return (R * c).toFixed(1);
}

// Initialize Leaflet Map
function initMap() {
  map = L.map('map', {
    center: NN_CENTER,
    zoom: 12,
    zoomControl: false
  });

  L.control.zoom({ position: 'topright' }).addTo(map);

  // OpenStreetMap standard tiles (Fast, crisp, Russian street labels, 100% free, no API key required)
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors',
    maxZoom: 19
  }).addTo(map);

  markersLayer = L.layerGroup().addTo(map);

  document.getElementById('btn-reset-map').addEventListener('click', () => {
    map.flyTo(NN_CENTER, 12, { duration: 1 });
  });
}

// Dynamically populate brand dropdown from actual loaded stations
function populateBrandSelect(stations) {
  const select = document.getElementById('brand-select');
  if (!select) return;

  const counts = {};
  stations.forEach(s => {
    const b = s.brand || 'Другие';
    counts[b] = (counts[b] || 0) + 1;
  });

  const prevVal = select.value;
  select.innerHTML = `<option value="all">Все сети (${stations.length} АЗС)</option>`;

  Object.keys(counts)
    .sort((a, b) => counts[b] - counts[a])
    .forEach(brand => {
      const opt = document.createElement('option');
      opt.value = brand;
      opt.textContent = `${brand} (${counts[brand]})`;
      select.appendChild(opt);
    });

  if (prevVal && (counts[prevVal] || prevVal === 'all')) {
    select.value = prevVal;
  }
}

// Fetch stations from backend API
async function loadStations() {
  const dot = document.getElementById('update-status-dot');
  const txt = document.getElementById('last-updated-text');
  
  dot.classList.add('updating');
  txt.textContent = 'Обновление данных...';

  try {
    const res = await fetch('/api/stations');
    const data = await res.json();
    
    allStations = data.stations || [];
    const updatedTime = data.updated_at ? new Date(data.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'недавно';
    
    txt.textContent = `Обновлено в ${updatedTime} (${allStations.length} АЗС)`;
    dot.classList.remove('updating');
    
    populateBrandSelect(allStations);
    applyFilters();
  } catch (err) {
    console.error('Failed to load stations:', err);
    txt.textContent = 'Ошибка загрузки данных';
    dot.classList.remove('updating');
  }
}

// Trigger force refresh
async function forceRefresh() {
  const btn = document.getElementById('btn-refresh');
  const dot = document.getElementById('update-status-dot');
  const txt = document.getElementById('last-updated-text');

  btn.disabled = true;
  dot.classList.add('updating');
  txt.textContent = 'Запрос к серверам АЗС...';

  try {
    const res = await fetch('/api/refresh', { method: 'POST' });
    const data = await res.json();
    
    if (res.ok) {
      setTimeout(loadStations, 3000);
    } else {
      alert(data.message || 'Ошибка обновления');
      dot.classList.remove('updating');
      txt.textContent = 'Лимит обновления: попробуйте позже';
    }
  } catch (err) {
    alert('Не удалось связаться с сервером');
    dot.classList.remove('updating');
  } finally {
    setTimeout(() => { btn.disabled = false; }, 5000);
  }
}

// Filter and sort stations
function applyFilters() {
  filteredStations = allStations.filter(s => {
    // Brand filter
    if (currentBrand !== 'all') {
      if (!s.brand.toLowerCase().includes(currentBrand.toLowerCase())) {
        return false;
      }
    }

    // Fuel filter & availability
    if (currentFuel !== 'all') {
      const fuelInfo = s.fuels ? s.fuels[currentFuel] : null;
      if (!fuelInfo) return false;
      if (onlyAvailable && !fuelInfo.available) return false;
    } else if (onlyAvailable) {
      const hasAnyAvail = s.fuels && Object.values(s.fuels).some(f => f && f.available);
      if (!hasAnyAvail) return false;
    }

    // Search query
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const match = (s.name && s.name.toLowerCase().includes(q)) ||
                    (s.address && s.address.toLowerCase().includes(q)) ||
                    (s.brand && s.brand.toLowerCase().includes(q));
      if (!match) return false;
    }

    return true;
  });

  // Calculate distances if user location is available
  if (userCoords) {
    filteredStations.forEach(s => {
      if (s.coords && s.coords.length === 2) {
        s._dist = parseFloat(calcDistance(userCoords[0], userCoords[1], s.coords[0], s.coords[1]));
      } else {
        s._dist = 9999;
      }
    });
    filteredStations.sort((a, b) => a._dist - b._dist);
  }

  // Update badges
  document.getElementById('station-count-badge').textContent = filteredStations.length;
  document.getElementById('list-count-val').textContent = filteredStations.length;

  renderMarkers();
  renderList();
}

// Render Leaflet Map Markers
function renderMarkers() {
  markersLayer.clearLayers();

  filteredStations.forEach(s => {
    if (!s.coords || s.coords.length < 2) return;
    const [lat, lon] = s.coords;

    const meta = getBrandMeta(s.brand);
    const isClosed = s.status === 'closed';
    const markerClass = isClosed ? 'marker-closed' : meta.cls;

    const icon = L.divIcon({
      className: `custom-az-marker ${markerClass}`,
      html: `<span>${meta.code}</span>`,
      iconSize: [34, 34],
      iconAnchor: [17, 17]
    });

    const marker = L.marker([lat, lon], { icon }).addTo(markersLayer);

    // Build popup content
    const popupHtml = buildPopupContent(s);
    marker.bindPopup(popupHtml, { maxWidth: 300, minWidth: 260 });

    marker.on('click', () => {
      highlightCard(s.id);
    });
  });
}

function buildPopupContent(s) {
  const meta = getBrandMeta(s.brand);
  const fuels = s.fuels || {};

  let fuelsHtml = '<div class="fuel-grid">';
  const fuelKeys = ['92', '95', '100', 'dt'];
  let stationHasLimit = null;
  fuelKeys.forEach(k => {
    const f = fuels[k];
    if (f) {
      const cls = f.available ? 'available' : 'unavailable';
      const label = k === 'dt' ? 'ДТ' : k;
      const limitHtml = f.limit ? `<div class="fuel-limit">${f.limit}</div>` : '';
      if (f.limit) stationHasLimit = f.limit;
      fuelsHtml += `
        <div class="fuel-item ${cls}">
          <div class="fuel-tag">${label}</div>
          <div class="fuel-price">${f.price > 0 ? f.price.toFixed(2) + ' ₽' : '—'}</div>
          ${limitHtml}
        </div>
      `;
    }
  });
  fuelsHtml += '</div>';

  const [lat, lon] = s.coords || [0, 0];
  const searchQuery = `${s.brand} ${s.name} ${s.address || ''}`.trim();
  const yandexUrl = `https://yandex.ru/maps/?text=${encodeURIComponent(searchQuery)}&ll=${lon}%2C${lat}&z=17`;
  const dgisUrl = `https://2gis.ru/n_novgorod/search/${encodeURIComponent(searchQuery)}`;
  const sourceName = s.source_name || (s.source === 'lukoil_api' ? 'API Ликард / Лукойл (v14)' : 'API Benzuber');

  const isLukoil = s.source === 'lukoil_api' || (s.brand && s.brand.includes('Лукойл'));
  const safeName = (s.name || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
  const safeAddr = (s.address || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
  const safeId = (s.id || '').replace(/'/g, "\\'");

  const verifyBtnHtml = isLukoil
    ? `<button type="button" class="verify-link" style="background:none; border:none; cursor:pointer; font-family:inherit; padding:0;" onclick="event.stopPropagation(); openLukoilModal('${safeId}', '${safeName}', '${safeAddr}');">ℹ️ О телеметрии &rarr;</button>`
    : (s.source_url
        ? `<a href="${s.source_url}" target="_blank" class="verify-link" onclick="event.stopPropagation();">🔍 Первоисточник &rarr;</a>`
        : '');

  return `
    <div style="padding: 6px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
        <span class="brand-badge ${meta.cardCls}">${s.brand}</span>
        ${stationHasLimit ? `<span class="badge-limit">⚠️ ${stationHasLimit}</span>` : ''}
        ${s._dist ? `<span style="font-size:11px; font-weight:700; color:#38bdf8;">${s._dist} км</span>` : ''}
      </div>
      <div style="font-size:14px; font-weight:700; color:#fff; margin-bottom:4px;">${s.name}</div>
      <div style="font-size:12px; color:#94a3b8; margin-bottom:10px;">${s.address}</div>
      ${fuelsHtml}
      <div style="display:flex; gap:6px; margin-top:8px;">
        <a href="${yandexUrl}" target="_blank" class="nav-btn nav-yandex" style="text-align:center;">Яндекс Карты</a>
        <a href="${dgisUrl}" target="_blank" class="nav-btn nav-2gis" style="text-align:center;">2ГИС</a>
      </div>
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px; padding-top:6px; border-top:1px solid rgba(255,255,255,0.08); font-size:11px;">
        <span style="color:#64748b;">📡 ${sourceName}</span>
        ${verifyBtnHtml}
      </div>
    </div>
  `;
}

// Render Station Cards in List View
function renderList() {
  const container = document.getElementById('stations-list');
  container.innerHTML = '';

  if (filteredStations.length === 0) {
    container.innerHTML = `
      <div style="text-align:center; padding: 40px 16px; color:#64748b;">
        <div style="font-size: 32px; margin-bottom:8px;">🔍</div>
        <div style="font-weight:600; color:#94a3b8;">По вашему запросу ничего не найдено</div>
        <div style="font-size:12px; margin-top:4px;">Попробуйте изменить марку топлива или сбросить фильтры</div>
      </div>
    `;
    return;
  }

  filteredStations.forEach(s => {
    const meta = getBrandMeta(s.brand);
    const card = document.createElement('div');
    card.className = 'station-card';
    card.id = `card-${s.id}`;

    const [lat, lon] = s.coords || [0, 0];
    const searchQuery = `${s.brand} ${s.name} ${s.address || ''}`.trim();
    const yandexUrl = `https://yandex.ru/maps/?text=${encodeURIComponent(searchQuery)}&ll=${lon}%2C${lat}&z=17`;
    const dgisUrl = `https://2gis.ru/n_novgorod/search/${encodeURIComponent(searchQuery)}`;
    const sourceName = s.source_name || (s.source === 'lukoil_api' ? 'API Ликард / Лукойл (v14)' : 'API Benzuber');

    const isLukoil = s.source === 'lukoil_api' || (s.brand && s.brand.includes('Лукойл'));
    const safeName = (s.name || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
    const safeAddr = (s.address || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
    const safeId = (s.id || '').replace(/'/g, "\\'");

    const verifyBtnHtml = isLukoil
      ? `<button type="button" class="verify-link" style="background:none; border:none; cursor:pointer; font-family:inherit; padding:0;" onclick="event.stopPropagation(); openLukoilModal('${safeId}', '${safeName}', '${safeAddr}');">ℹ️ О телеметрии &rarr;</button>`
      : (s.source_url
          ? `<a href="${s.source_url}" target="_blank" class="verify-link" onclick="event.stopPropagation();">🔍 Первоисточник &rarr;</a>`
          : '');

    let fuelsHtml = '<div class="fuel-grid">';
    const fuelKeys = ['92', '95', '100', 'dt'];
    let stationHasLimit = null;
    fuelKeys.forEach(k => {
      const f = (s.fuels || {})[k];
      const cls = (f && f.available) ? 'available' : 'unavailable';
      const label = k === 'dt' ? 'ДТ' : k;
      const priceText = (f && f.price > 0) ? `${f.price.toFixed(2)} ₽` : '—';
      const limitHtml = (f && f.limit) ? `<div class="fuel-limit">${f.limit}</div>` : '';
      if (f && f.limit) stationHasLimit = f.limit;
      fuelsHtml += `
        <div class="fuel-item ${cls}">
          <div class="fuel-tag">${label}</div>
          <div class="fuel-price">${priceText}</div>
          ${limitHtml}
        </div>
      `;
    });
    fuelsHtml += '</div>';

    card.innerHTML = `
      <div class="card-top">
        <span class="brand-badge ${meta.cardCls}">${s.brand}</span>
        ${stationHasLimit ? `<span class="badge-limit">⚠️ ${stationHasLimit}</span>` : ''}
        ${s._dist ? `<span class="distance-badge">${s._dist} км</span>` : ''}
      </div>
      <div class="card-title">${s.name}</div>
      <div class="card-address">${s.address}</div>
      ${fuelsHtml}
      <div class="card-actions">
        <a href="${yandexUrl}" target="_blank" class="nav-btn nav-yandex" onclick="event.stopPropagation();">
          Яндекс Карты
        </a>
        <a href="${dgisUrl}" target="_blank" class="nav-btn nav-2gis" onclick="event.stopPropagation();">
          2ГИС
        </a>
      </div>
      <div class="card-meta">
        <span class="source-tag">📡 ${sourceName}</span>
        ${verifyBtnHtml}
      </div>
    `;

    card.addEventListener('click', () => {
      // Switch to map view on mobile and focus marker
      if (window.innerWidth <= 900) {
        setViewMode('map');
      }
      if (s.coords && s.coords.length === 2) {
        map.flyTo(s.coords, 15, { duration: 0.8 });
      }
    });

    container.appendChild(card);
  });
}

function highlightCard(stationId) {
  document.querySelectorAll('.station-card').forEach(c => c.classList.remove('active-card'));
  const card = document.getElementById(`card-${stationId}`);
  if (card) {
    card.classList.add('active-card');
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

// User Geolocation
function locateUser() {
  if (!navigator.geolocation) {
    alert('Геолокация не поддерживается вашим браузером');
    return;
  }

  const btn = document.getElementById('btn-locate');
  btn.style.color = '#38bdf8';

  navigator.geolocation.getCurrentPosition(
    pos => {
      userCoords = [pos.coords.latitude, pos.coords.longitude];

      if (userMarker) {
        map.removeLayer(userMarker);
      }

      // Blue pulse icon for user location
      const userIcon = L.divIcon({
        className: 'custom-az-marker',
        html: `<div style="width:16px; height:16px; background:#38bdf8; border:3px solid #fff; border-radius:50%; box-shadow:0 0 12px #38bdf8;"></div>`,
        iconSize: [22, 22],
        iconAnchor: [11, 11]
      });

      userMarker = L.marker(userCoords, { icon: userIcon }).addTo(map);
      userMarker.bindPopup('<b>Вы здесь</b>').openPopup();

      map.flyTo(userCoords, 14, { duration: 1 });
      applyFilters();
    },
    err => {
      console.warn('Geolocation error:', err);
      alert('Не удалось получить геопозицию. Проверьте разрешение в браузере.');
      btn.style.color = '';
    },
    { enableHighAccuracy: true, timeout: 8000 }
  );
}

// Lukoil Verification Modal Handlers
function openLukoilModal(id, name, address) {
  const nameEl = document.getElementById('modal-st-name');
  const addrEl = document.getElementById('modal-st-addr');
  const idEl = document.getElementById('modal-st-id');
  if (nameEl) nameEl.textContent = name || 'АЗС Лукойл';
  if (addrEl) addrEl.textContent = address || 'Нижний Новгород';
  if (idEl) idEl.textContent = id ? id.replace('lukoil_', '') : '—';
  const modal = document.getElementById('lukoil-modal');
  if (modal) modal.style.display = 'flex';
}

function closeLukoilModal() {
  const modal = document.getElementById('lukoil-modal');
  if (modal) modal.style.display = 'none';
}

// View Mode Switcher (Desktop: Map / Split | Mobile: Map / List)
function setViewMode(mode) {
  const isMobile = window.innerWidth <= 900;
  if (!isMobile && mode === 'list') {
    mode = 'split';
  } else if (isMobile && mode === 'split') {
    mode = 'map';
  }

  currentView = mode;
  const sidebar = document.getElementById('sidebar-panel');
  const mapWrapper = document.getElementById('map-wrapper');
  const btnMap = document.getElementById('view-map-btn');
  const btnSplit = document.getElementById('view-split-btn');
  const btnList = document.getElementById('view-list-btn');

  // Reset classes
  sidebar.classList.remove('mobile-visible', 'hidden-view', 'full-width');
  mapWrapper.classList.remove('mobile-hidden', 'hidden-view', 'full-width');
  if (btnMap) btnMap.classList.remove('active');
  if (btnSplit) btnSplit.classList.remove('active');
  if (btnList) btnList.classList.remove('active');

  if (isMobile) {
    if (mode === 'list') {
      sidebar.classList.add('mobile-visible');
      mapWrapper.classList.add('mobile-hidden');
      if (btnList) btnList.classList.add('active');
    } else {
      sidebar.classList.remove('mobile-visible');
      mapWrapper.classList.remove('mobile-hidden');
      if (btnMap) btnMap.classList.add('active');
      if (map) setTimeout(() => map.invalidateSize(), 150);
    }
  } else {
    // Desktop / Laptop (>900px): only Map and Split
    if (mode === 'map') {
      sidebar.classList.add('hidden-view');
      mapWrapper.classList.add('full-width');
      if (btnMap) btnMap.classList.add('active');
    } else {
      // 'split' (side by side default)
      if (btnSplit) btnSplit.classList.add('active');
    }
    if (map) setTimeout(() => map.invalidateSize(), 150);
  }
}

// Event Listeners setup
function setupEvents() {
  // Fuel pills
  document.getElementById('fuel-pills').addEventListener('click', e => {
    if (e.target.classList.contains('pill')) {
      document.querySelectorAll('#fuel-pills .pill').forEach(p => p.classList.remove('active'));
      e.target.classList.add('active');
      currentFuel = e.target.dataset.fuel;
      applyFilters();
    }
  });

  // Brand dropdown
  document.getElementById('brand-select').addEventListener('change', e => {
    currentBrand = e.target.value;
    applyFilters();
  });

  // Only available checkbox
  document.getElementById('only-available-check').addEventListener('change', e => {
    onlyAvailable = e.target.checked;
    applyFilters();
  });

  // Search input
  const searchInput = document.getElementById('search-input');
  const clearBtn = document.getElementById('clear-search-btn');

  searchInput.addEventListener('input', e => {
    searchQuery = e.target.value.trim();
    clearBtn.style.display = searchQuery ? 'block' : 'none';
    applyFilters();
  });

  clearBtn.addEventListener('click', () => {
    searchInput.value = '';
    searchQuery = '';
    clearBtn.style.display = 'none';
    applyFilters();
  });

  // Geolocation button
  document.getElementById('btn-locate').addEventListener('click', locateUser);

  // Force Refresh button
  document.getElementById('btn-refresh').addEventListener('click', forceRefresh);

  // View toggle buttons (Desktop + Mobile)
  document.getElementById('view-map-btn').addEventListener('click', () => setViewMode('map'));
  const splitBtn = document.getElementById('view-split-btn');
  if (splitBtn) {
    splitBtn.addEventListener('click', () => setViewMode('split'));
  }
  const listBtn = document.getElementById('view-list-btn');
  if (listBtn) {
    listBtn.addEventListener('click', () => setViewMode('list'));
  }

  // Lukoil Modal Events
  const closeBtn = document.getElementById('btn-close-modal');
  if (closeBtn) closeBtn.addEventListener('click', closeLukoilModal);
  const okBtn = document.getElementById('btn-modal-ok');
  if (okBtn) okBtn.addEventListener('click', closeLukoilModal);
  const modal = document.getElementById('lukoil-modal');
  if (modal) {
    modal.addEventListener('click', e => {
      if (e.target === modal) closeLukoilModal();
    });
  }

  // Window resize listener to gracefully adapt view
  window.addEventListener('resize', () => {
    const isMobile = window.innerWidth <= 900;
    if (isMobile && currentView === 'split') {
      setViewMode('map');
    } else if (!isMobile && currentView === 'list') {
      setViewMode('split');
    }
  });
}

// Document Ready
document.addEventListener('DOMContentLoaded', () => {
  initMap();
  setupEvents();
  const initialMode = window.innerWidth <= 900 ? 'map' : 'split';
  setViewMode(initialMode);
  loadStations();
});
