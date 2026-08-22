# Аналитика игрового поведения

Игра ведёт append-only журнал ключевых действий в SQLite-таблице `analytics_events`.

Главная цель журнала — позволить анализировать реальное поведение игроков после накопления статистики: какие механики используются, какие игнорируются, где игроки умирают или прекращают вылазки, какие товары покупают и какие решения выбирают в событиях.

## Принципы

- Аналитика не участвует в расчёте игрового состояния.
- Во время обычной игры события только добавляются (`INSERT`) и не редактируются задним числом.
- `/reset` — административный полный сброс: он удаляет и состояние персонажа, и всю его историю из `analytics_events`.
- Username и тексты Telegram-сообщений не сохраняются.
- Каждая вылазка и каждая поездка получает собственный `run_id`, общий для событий внутри этого прохождения.
- `game_version` позволяет разделять статистику, собранную на разных версиях механик и баланса.

## Таблица `analytics_events`

| Поле | Назначение |
| --- | --- |
| `id` | последовательный ID события |
| `telegram_id` | идентификатор игрока |
| `event_time` | UTC-время события |
| `event_name` | тип события |
| `context` | подсистема: expedition, combat, travel, market и т.д. |
| `run_id` | ID конкретной вылазки/дороги, если применимо |
| `entity_id` | объект действия: сектор, враг, товар, характеристика, боевое действие |
| `value` | основное числовое значение события, если оно есть |
| `metadata` | JSON с дополнительным контекстом и снимком состояния игрока |
| `game_version` | версия механик на момент события |

Во все события, пока персонаж существует, автоматически добавляется базовый снимок состояния: `state`, `level`, `xp`, `hp`, `credits`, `ammo`, `medkits`, `threat`, `steps`, `weapon_id`, `armor_id`, `location_id`.

## Основные события

### Система и персонаж

- `player_created` — первый персонаж игрока после создания или полного административного сброса.
- `character_recreated` — персонаж создан заново после удаления игрового состояния при сохранённой аналитике; в штатном `/reset` сейчас не используется, потому что reset удаляет аналитику.
- `attribute_upgraded` — повышение характеристики. `entity_id` содержит характеристику, `value` — новое значение.

### Вылазки

- `expedition_started` — начало вылазки. `entity_id` = сектор.
- `expedition_explored` — нажатие исследования. `value` = угроза после шага; в metadata есть тип выпавшего события и номер шага.
- `scene_choice` — выбор в сценарной встрече.
- `special_event_resolved` — решение по аномалии/тайнику.
- `sector_completed` — сектор впервые доведён до 100%.
- `expedition_returned` — добровольное успешное возвращение; `value` = стоимость склада после закрепления добычи.

### Бой

- `combat_started` — начало боя после вылазочного/дорожного события.
- `combat_action` — выбранное действие игрока (`shoot`, `burst`, `melee`, `cover`, `medkit`, `flee`, `wait`). `value` = нанесённый урон, если применимо.
- `combat_finished` — исход боя: victory / fled / death.
- `player_died` — смерть персонажа с причиной в `entity_id` и metadata.

### Дороги

- `travel_started` — начало маршрута.
- `travel_advanced` — прохождение очередного участка; `value` = позиция на маршруте в текущем направлении.
- `travel_turned` — игрок развернулся на дороге. В metadata сохраняются прежняя и новая цель, позиция до/после разворота и признак мгновенного возврата до первого участка.
- `travel_finished` — прибытие в поселение; при мгновенной отмене поездки до первого участка `outcome = returned_before_first_section`.

### Экономика

- `market_bought` — покупка ресурса на рынке; `value` = потраченные жетоны.
- `market_sold_cargo` — продажа торгового груза; `value` = полученные жетоны, состав груза хранится в metadata.
- `stash_loaded_to_cargo` — перенос ресурсов со склада в груз.
- `cargo_unloaded_to_stash` — разгрузка торгового груза.
- `stash_sold` — продажа ресурсов со склада.
- `shop_bought` — покупка оружия, экипировки, патронов или аптечки у торговца.

## Примеры будущего анализа

Частота боевых действий:

```sql
SELECT entity_id AS action, COUNT(*) AS uses
FROM analytics_events
WHERE event_name = 'combat_action'
GROUP BY entity_id
ORDER BY uses DESC;
```

Какие сектора чаще всего бросают раньше 100 угрозы:

```sql
SELECT entity_id AS sector,
       COUNT(*) AS returns,
       AVG(CAST(json_extract(metadata, '$.final_threat') AS REAL)) AS avg_final_threat
FROM analytics_events
WHERE event_name = 'expedition_returned'
GROUP BY entity_id
ORDER BY avg_final_threat;
```

Смертность по врагам:

```sql
SELECT entity_id AS cause, COUNT(*) AS deaths
FROM analytics_events
WHERE event_name = 'player_died'
  AND entity_id LIKE 'combat:%'
GROUP BY entity_id
ORDER BY deaths DESC;
```

Использование сценарных решений:

```sql
SELECT entity_id AS scene,
       json_extract(metadata, '$.action') AS action,
       COUNT(*) AS uses
FROM analytics_events
WHERE event_name = 'scene_choice'
GROUP BY scene, action
ORDER BY scene, uses DESC;
```

## Передача данных для анализа

Для полного анализа достаточно передать SQLite-файл игры. Если нужно передавать только аналитику, можно экспортировать таблицу `analytics_events` отдельно в CSV/JSON или сделать копию базы, содержащую только эту таблицу.

При сравнении поведения между изменениями механик всегда группировать или фильтровать данные по `game_version`, чтобы не смешивать несовместимые версии баланса.
