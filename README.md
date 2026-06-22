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

На каждый аккаунт (всегда видны на устройстве, например **Kiko**):

- `sensor.*_active_orders` — число активных заказов
- `sensor.*_order_status` — статус заказа (`none` если заказов нет)
- `sensor.*_courier_eta` — минут до курьера (`unknown`, пока нет ETA)
- `binary_sensor.*_courier_nearby` — курьер рядом (`off`, если заказов нет)
- `sensor.*_past_orders_eda` / `*_past_orders_delivery` / `*_past_orders_lavka` — число заказов в истории по сервису (с пагинацией API, до ~2000)

При нескольких заказах показывается «главный»: сначала с курьером рядом, иначе с наименьшим ETA.

### Автоматизация

Курьер близко — фиксированный `entity_id`, id заказа менять не нужно:

```yaml
alias: Курьер рядом
trigger:
  - platform: state
    entity_id: binary_sensor.kiko_courier_nearby
    from: "off"
    to: "on"
action:
  - service: notify.kikophone
    data:
      message: "Курьер Яндекс Еды почти у двери"
```

Курьер через ≤ 5 минут:

```yaml
alias: Курьер через 5 минут
trigger:
  - platform: numeric_state
    entity_id: sensor.kiko_courier_eta
    below: 6
condition:
  - condition: template
    value_template: >
      {{ states('sensor.kiko_order_status') not in ['none', 'closed', 'unknown', 'unavailable'] }}
action:
  - service: notify.kikophone
    data:
      message: "Курьер через {{ states('sensor.kiko_courier_eta') }} мин"
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
