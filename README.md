# yandex_eat

Неофициальная интеграция Home Assistant и CLI для отслеживания заказов **Яндекс Еда**, **Деливери** и **Лавка**.

Опрос API `tracked-orders` (без push-уведомлений). Авторизация через **QR-код** или **x-token** (как в [Yandex Station](https://github.com/AlexxIT/YandexStation)). Поддерживается **несколько аккаунтов** — добавьте интеграцию повторно для каждого логина.

## Установка через HACS

1. В HACS: **Настройки** → **Пользовательские репозитории** → тип **Integration** → `https://github.com/KikoGmaes/hass_yandex_eat`
2. **HACS** → **Интеграции** → **Yandex Eat** → **Скачать**.
3. Перезагрузите Home Assistant.
4. **Настройки** → **Устройства и службы** → **Добавить интеграцию** → **Yandex Eat**.

### Авторизация

| Способ | Как |
|--------|-----|
| **QR-код** | Отсканируйте QR в приложении Яндекс (профиль → добавить аккаунт) |
| **Токен** | Вставьте `x_token` из интеграции Yandex Station или из `core.config_entries` |

Чтобы добавить **второй аккаунт**, снова добавьте интеграцию Yandex Eat — каждый логин создаёт отдельную запись.

### Сущности

На каждый аккаунт:

- `sensor.*_active_orders` — число активных заказов
- `sensor.*_<order>_status` — статус заказа (`assembling`, `performer_found`, `delivery_arrived`, …)
- `binary_sensor.*_<order>_courier_nearby` — курьер рядом (`delivery_arrived` или ETA ≤ 5 мин)

### Автоматизация

```yaml
alias: Курьер у двери
trigger:
  - platform: state
    entity_id: binary_sensor.k1f234_abc123_courier_nearby
    to: "on"
action:
  - service: notify.mobile_app_phone
    data:
      message: "Курьер Яндекс Еды у двери"
```

### Настройки

**Настроить** → интервал опроса (15–300 сек, по умолчанию 30).

---

## CLI (опционально)

```powershell
cd d:\Work\yandex_eat
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

Скопируйте `.env.example` → `.env`, вставьте `YANDEX_X_TOKEN`.

```powershell
yandex-eat login
yandex-eat track
yandex-eat track --service eda
yandex-eat track --nearby
yandex-eat track --json
```

## API

```
GET https://eda.yandex.ru/api/v1/providers/orders/v1/tracked-orders   # Еда + Деливери
GET https://lavka.yandex.ru/api/v1/providers/orders/v1/tracked-orders # Лавка
```

Auth: session cookies после обмена `x-token` через `mobileproxy.passport.yandex.net`.

## Структура репозитория (HACS)

```
hacs.json
README.md
custom_components/yandex_eat/
  __init__.py
  manifest.json
  config_flow.py
  ...
```

## Разработка

Интеграция не входит в default HACS — добавляется как custom repository. Для публикации в default store см. [HACS publish docs](https://www.hacs.xyz/docs/publish/integration/).
