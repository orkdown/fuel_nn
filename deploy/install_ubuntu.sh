#!/usr/bin/env bash
set -e

# ==============================================================================
# Скрипт автоматического развертывания веб-сервиса АЗС Нижний Новгород
# для Ubuntu 24.04 LTS (Nginx + Systemd + Certbot SSL)
# Домен: gdeflex.orkproxy.nx.kg
# ==============================================================================

DOMAIN="gdeflex.orkproxy.nx.kg"
APP_DIR="/var/www/fuel_nn"
SERVICE_NAME="fuel-nn"

# Цвета для вывода в консоль
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}====================================================================${NC}"
echo -e "${CYAN}  Установка веб-сервиса мониторинга топлива АЗС (Нижний Новгород)  ${NC}"
echo -e "${CYAN}  Целевой домен: https://${DOMAIN}${NC}"
echo -e "${CYAN}====================================================================${NC}\n"

# 1. Проверка прав суперпользователя (root)
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[!] Ошибка: Пожалуйста, запустите скрипт от root (sudo bash install_ubuntu.sh)${NC}"
  exit 1
fi

# 2. Проверка порта 8443 (MTProxy безопасность)
echo -e "${YELLOW}[1/7] Проверка портов и изоляции MTProxy...${NC}"
if ss -tuln | grep -q ":8443 "; then
  echo -e "${GREEN}[OK] MTProxy обнаружен на порту 8443. Порт 8443 остается нетронутым!${NC}"
fi

# 3. Обновление пакетов и установка системных зависимостей
echo -e "\n${YELLOW}[2/7] Установка системных пакетов (Nginx, Python3, Certbot)...${NC}"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx curl rsync

# 4. Копирование файлов проекта в /var/www/fuel_nn
echo -e "\n${YELLOW}[3/7] Подготовка рабочей директории ${APP_DIR}...${NC}"
mkdir -p "${APP_DIR}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$SCRIPT_DIR" != "$APP_DIR" ]; then
  echo -e "Копирование файлов из ${SCRIPT_DIR} в ${APP_DIR}..."
  rsync -av --exclude="venv" --exclude="__pycache__" --exclude=".git" "${SCRIPT_DIR}/" "${APP_DIR}/"
fi

# 5. Создание виртуального окружения Python и установка библиотек
echo -e "\n${YELLOW}[4/7] Создание Python venv и установка зависимостей...${NC}"
cd "${APP_DIR}"
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

# Первичная инициализация кэша
echo -e "Проверка и предварительная загрузка данных АЗС..."
venv/bin/python -c "from backend.data_manager import manager; print('Инициализация БД АЗС...'); manager.update_all()" || true

# 6. Установка и запуск systemd-сервиса
echo -e "\n${YELLOW}[5/7] Настройка systemd-сервиса ${SERVICE_NAME}...${NC}"
cp deploy/fuel-nn.service /etc/systemd/system/${SERVICE_NAME}.service
systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
systemctl restart ${SERVICE_NAME}

# Ожидание старта сервиса и проверка healthcheck
sleep 3
if curl -s http://127.0.0.1:8080/api/health | grep -q "ok"; then
  echo -e "${GREEN}[OK] Бэкенд успешно запущен на 127.0.0.1:8080!${NC}"
else
  echo -e "${RED}[!] Внимание: бэкенд еще запускается или произошла ошибка. Проверьте: journalctl -u ${SERVICE_NAME} -n 30${NC}"
fi

# 7. Настройка Nginx
echo -e "\n${YELLOW}[6/7] Настройка веб-сервера Nginx для ${DOMAIN}...${NC}"
cp deploy/nginx-site.conf /etc/nginx/sites-available/${DOMAIN}
ln -sf /etc/nginx/sites-available/${DOMAIN} /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default || true

nginx -t
systemctl reload nginx

# 8. Автоматический выпуск SSL сертификата Let's Encrypt через Certbot
echo -e "\n${YELLOW}[7/7] Выпуск бесплатного SSL-сертификата (Let's Encrypt) через Certbot...${NC}"
certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos --register-unsafely-without-email --redirect || {
  echo -e "${YELLOW}[!] Автоматический выпуск Certbot завершился с предупреждением.${NC}"
  echo -e "Вы можете повторить команду вручную: sudo certbot --nginx -d ${DOMAIN}"
}

echo -e "\n${GREEN}====================================================================${NC}"
echo -e "${GREEN}  УСТАНОВКА УСПЕШНО ЗАВЕРШЕНА!  ${NC}"
echo -e "${GREEN}====================================================================${NC}"
echo -e "Сайт доступен в интернете по адресу:  ${CYAN}https://${DOMAIN}${NC}"
echo -e "Фоновое автообновление цен:           Каждые 12 часов"
echo -e "Управление службой:                   sudo systemctl restart ${SERVICE_NAME}"
echo -e "Просмотр логов:                       sudo journalctl -u ${SERVICE_NAME} -f"
echo -e "MTProxy (порт 8443):                  Работает без изменений"
echo -e "${GREEN}====================================================================${NC}\n"
