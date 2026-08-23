# NIGHTSHIFT: журнал действий и игровых событий

## Зачем он нужен

`analytics_events` — отдельный событийный журнал для последующего анализа поведения игроков и качества игрового баланса.

Он не заменяет `ledger`, `orders`, `disputes` или другие предметные таблицы. Эти таблицы хранят текущее состояние и бизнес-факты симуляции, а `analytics_events` хранит последовательность действий и событий во времени.

Главные задачи журнала:

- понимать, какими разделами и механиками реально пользуются игроки;
- строить воронки найма, закупки, распределения и диспутов;
- измерять время между появлением проблемы и реакцией игрока;
- оценивать влияние push-уведомлений на возврат в игру;
- искать места, где игроки бросают сценарий или часто возвращаются назад;
- сравнивать разные прохождения одного тестового аккаунта;
- связывать решения игрока с последующим изменением денег, рейтинга, диспутов и отзывов;
- в дальнейшем подбирать баланс на основании реальных данных, а не только субъективных ощущений.

## Таблица `analytics_events`

Поля:

- `id` — монотонный идентификатор события;
- `player_id` — Telegram ID игрока;
- `run_id` — идентификатор конкретного прохождения;
- `event_kind` — крупный класс события;
- `event_name` — стабильное техническое название события;
- `source` — подсистема, породившая запись;
- `entity_type` — тип связанной сущности;
- `entity_id` — ID связанной сущности;
- `balance` — snapshot баланса магазина в момент записи;
- `rating` — snapshot рейтинга;
- `time_multiplier` — текущий персональный множитель времени;
- `payload_json` — дополнительные параметры события;
- `created_at` — реальное время события.

Для текущего MVP `run_id` соответствует времени создания текущего магазина (`shops.created_at`). После `/reset` создаётся новый магазин и последующие события относятся к новому прохождению.

## Почему таблица не связана FK с `shops`

Это намеренно.

`/reset` должен полностью удалить игровой прогресс, но не аналитическую историю. Поэтому у `analytics_events.player_id` нет `FOREIGN KEY ... ON DELETE CASCADE`.

Перед удалением магазина trigger записывает `progress_reset`. Затем игровой state удаляется, но вся последовательность действий старого прохождения остаётся в `analytics_events`.

Так можно сравнивать несколько тестовых прохождений одного игрока.

## Классы событий

### `player_action`

Действие, инициированное человеком через Telegram.

Автоматически логируются:

- slash-команды;
- inline callback-кнопки;
- обычные текстовые сообщения как факт ввода текста.

Для обычного текста журнал сохраняет только длину, а не содержимое сообщения.

Callback ID нормализуются, чтобы ID сущностей не раздували кардинальность метрик.

Например:

```text
workflow:alloc:123:456:10
```

становится:

```text
callback.workflow.alloc.*.*.*
```

При этом исходный callback сохраняется в `payload_json`, если позже потребуется детальный разбор конкретного тестового прохождения.

### `game_event`

Событие, возникшее из состояния игры или зафиксированное после изменения данных.

Основные события:

- `supplier_offer_created`;
- `batch_created`;
- `batch_responsibility_changed`;
- `employee_task_started`;
- `employee_task_status_changed`;
- `retail_allocation_created`;
- `retail_allocation_status_changed`;
- `retail_positions_published`;
- `order_created`;
- `dispute_opened`;
- `dispute_resolved`;
- `review_created`;
- `inbox_created`;
- `ledger_entry_created`;
- `payroll_processed`;
- `recruitment_campaign_started`;
- `recruitment_campaign_completed`;
- `candidate_created`;
- `employee_added`;
- `employee_role_changed`;
- `employee_deactivated`;
- `listing_price_changed`;
- `packaging_rule_changed`;
- `time_multiplier_changed`;
- `notification_sent`;
- `progress_reset`.

События состояния в основном создаются SQLite-trigger-ами. Благодаря этому они фиксируются и тогда, когда симуляция меняет мир в фоне без открытого Telegram-интерфейса.

## Push-аналитика

После успешной отправки важного или срочного уведомления создаётся:

```text
notification_sent
```

В payload сохраняются:

- тип входящего;
- priority;
- `inbox_id` через `entity_id`.

После этого можно сопоставить уведомление с последующими callback-действиями игрока и оценивать, какие типы событий действительно возвращают человека в игру.

## Snapshot состояния

Почти каждая запись содержит текущие:

- `balance`;
- `rating`;
- `time_multiplier`.

Это упрощает временной анализ. Для многих задач не потребуется восстанавливать историческое состояние магазина из десятков отдельных таблиц.

## Отказоустойчивость

Аналитика не должна ломать игру.

Middleware перехватывает собственные ошибки записи и не прерывает игровой callback. Ошибка аналитического логирования не должна мешать игроку открыть меню, принять решение или совершить покупку.

Предметные SQLite-trigger-ы выполняются в той же транзакции, что и изменение игрового состояния. Поэтому события вроде нового заказа или диспута синхронны соответствующему факту в БД.

## Примеры запросов

### Самые используемые действия

```sql
SELECT event_name, COUNT(*) AS actions
FROM analytics_events
WHERE event_kind = 'player_action'
GROUP BY event_name
ORDER BY actions DESC;
```

### Действия по отдельным прохождениям

```sql
SELECT run_id, COUNT(*) AS actions,
       MIN(created_at) AS started_at,
       MAX(created_at) AS last_event_at
FROM analytics_events
WHERE player_id = ?
GROUP BY run_id
ORDER BY started_at;
```

### Воронка найма

```sql
SELECT event_name, COUNT(*) AS events
FROM analytics_events
WHERE event_name IN (
    'recruitment_campaign_started',
    'recruitment_campaign_completed',
    'candidate_created',
    'employee_added'
)
GROUP BY event_name;
```

### Диспуты и решения

```sql
SELECT
    json_extract(payload_json, '$.decision') AS decision,
    json_extract(payload_json, '$.refund_source') AS source,
    COUNT(*) AS cases,
    AVG(json_extract(payload_json, '$.refund_amount')) AS avg_refund
FROM analytics_events
WHERE event_name = 'dispute_resolved'
GROUP BY decision, source;
```

### Использование ускорения во время тестов

```sql
SELECT time_multiplier, COUNT(*) AS events
FROM analytics_events
WHERE player_id = ?
GROUP BY time_multiplier
ORDER BY time_multiplier;
```

## Принцип дальнейшего развития

При добавлении новой значимой механики нужно решить два вопроса:

1. какое действие игрока показывает его намерение;
2. какое игровое событие показывает фактический результат.

Например для новой инвестиционной механики недостаточно записать только `callback.invest.buy`: отдельно нужен факт успешного создания инвестиции и, позднее, её результат.

Так журнал останется пригодным для причинно-следственного анализа, а не превратится в набор технических кликов.