# Модель данных SQLite

## Общая схема

```text
shops
 ├── settings
 ├── employees
 │    ├── employee_tasks
 │    ├── packaging_rules
 │    ├── retail_allocations
 │    └── retail_positions
 ├── candidates
 ├── recruitment_drafts
 ├── recruitment_campaigns
 ├── payroll_runs
 ├── clients
 ├── supplier_offers ── suppliers
 ├── batches ────────── suppliers + products + responsible employee
 ├── listings ───────── products
 ├── orders ─────────── clients + retail employees + batches + products
 │    ├── disputes
 │    └── reviews
 ├── inbox
 └── ledger

analytics_events  ← отдельная persistent event history, переживает /reset
```

Все пользовательские игровые сущности привязаны к `player_id`. `/reset` удаляет `shops.player_id`, после чего зависимые данные конкретного игрока удаляются каскадно и создаётся новый старт.

`analytics_events` является исключением: у неё намеренно нет внешнего ключа на `shops`, поэтому аналитическая история не удаляется вместе с прогрессом.

## shops

Главное состояние магазина.

Основные поля:

- `balance` — фактический денежный остаток;
- `reserve_target` — целевой резерв;
- `rating` — клиентский рейтинг;
- `last_simulated_at` — последняя точка симуляции;
- `total_revenue`, `total_profit`, `total_orders` — lifetime-метрики.

Свободные деньги:

`balance - employee_deposits - wages_accrued - reserve_target`

Депозиты сотрудников являются обязательствами: деньги физически находятся у магазина, но не считаются свободным капиталом.

## settings

Персональные настройки игрока:

- `time_multiplier`;
- `last_payroll_at`;
- настройки уведомлений;
- задел под автоматизацию решений.

`time_multiplier` влияет на игровые задачи и дедлайны, но не ускоряет payroll, который происходит раз в реальные 24 часа.

## employees

Видимые поля:

- `alias`;
- `role`;
- `pay_per_job`;
- `deposit`;
- `deposit_contribution_pct`;
- `wages_accrued`;
- `total_wages_paid`;
- `deposit_from_wages`;
- `has_car`;
- `jobs_done`;
- `disputes`;
- `losses`;
- `active`, `available`;
- `joined_at`.

Скрытые параметры:

- `reliability`;
- `attention`;
- `honesty`;
- `loyalty`;
- `stress`.

Роли:

- `courier` — розничный сотрудник;
- `warehouse` — оптовый сотрудник.

Смена роли не меняет накопленную историю или депозит, но устанавливает базовую ставку новой роли.

## employee_tasks

Очередь асинхронных рабочих задач сотрудников.

Поля:

- `employee_id`;
- `kind`;
- `status`;
- `batch_id`;
- `allocation_id`;
- `product_id`;
- `quantity`;
- `started_at`;
- `completes_at`;
- `note`.

Текущие виды задач:

- `receive_batch` — оптовый сотрудник принимает новую партию;
- `handoff` — оптовый сотрудник готовит назначенный объём для розничного;
- `prepare_positions` — розничный сотрудник готовит позиции к публикации.

`/speed` пересчитывает оставшееся реальное время этих задач, сохраняя их игровую длительность. `/tick` также проматывает задачи.

## batches

Отдельная закупленная партия.

Поля:

- `quantity` — исходный объём;
- `remaining` — объём, который всё ещё находится у оптового сотрудника;
- `unit_cost`;
- `quality`;
- `supplier_id`;
- `product_id`;
- `responsible_employee_id`;
- `status`.

Статусы, важные для workflow:

- `receiving` — новая партия ещё находится в активной задаче приёма;
- `warehouse` — готова к ручному распределению;
- `lost` — остаток утрачен.

При распределении рознице `remaining` уменьшается, а назначенный объём переходит в `retail_allocations`.

После потери сотрудника у сохранившейся части партии `responsible_employee_id` может стать `NULL`. Такие партии показываются в `Команда → Без ответственного`.

## retail_allocations

Ручное назначение части партии конкретному розничному сотруднику.

Поля:

- `batch_id`;
- `wholesale_employee_id`;
- `retail_employee_id`;
- `product_id`;
- `quantity`;
- `unit_cost`;
- `quality`;
- `status`;
- timestamps.

Статусы:

- `waiting` — оптовый сотрудник ещё выполняет задачу передачи;
- `preparing` — розничный сотрудник уже получил назначение и готовит позиции;
- `published` — позиции созданы;
- `lost` — часть или весь объём потерян;
- `blocked` — переход не завершился из-за недоступности сотрудника.

`retail_allocations` сохраняют происхождение товара от конкретной партии до конкретного розничного сотрудника.

## packaging_rules

Правила фасовок конкретного розничного сотрудника по конкретному товару.

Уникальный ключ:

`player_id + employee_id + product_id`

Поля:

- `pct_1`;
- `pct_2`;
- `pct_5`.

Сумма всегда должна быть 100%.

Стандарт:

`60 / 30 / 10`

Правила применяются только в момент завершения `prepare_positions`. Уже опубликованные позиции не меняются задним числом.

## retail_positions

Единственный продаваемый товарный слой.

Поля:

- `allocation_id`;
- `batch_id`;
- `employee_id` — розничный сотрудник;
- `product_id`;
- `pack_size`;
- `position_count`;
- `unit_cost`;
- `quality`.

Продажа больше не списывает товар напрямую из `batches`.

Доступное количество конкретной фасовки на витрине:

`SUM(retail_positions.position_count)`

Объём товара на витрине:

`SUM(position_count × pack_size)`

При продаже `position_count` уменьшается на 1, а заказ получает `batch_id` и `employee_id` исходной позиции.

## Экспозиция сотрудника и депозит

Депозит не блокирует назначение товара.

`exposure` — себестоимость товара, который сейчас находится под ответственностью сотрудника.

Для оптового сотрудника:

- остатки партий;
- ожидающие передачи рознице объёмы.

Для розничного сотрудника:

- объёмы `preparing`;
- опубликованные, но не проданные позиции.

Непокрытая стоимость:

`unsecured = MAX(0, exposure - deposit)`

Если `unsecured > 0`, сотрудник остаётся работоспособным, но симуляция включает риск потери товара.

## Потеря товара сотрудником

При срабатывании риска:

- часть или весь товар сотрудника списывается;
- невзятый остаток по возможности возвращается в доступный контур;
- сотрудник становится неактивным;
- активные задачи отменяются;
- `deposit` становится 0, потому что оставшийся депозит удерживается магазином;
- во входящие создаётся срочное кадровое событие;
- потеря учитывается в `losses` и `total_profit`.

Сам депозит не создаёт новый денежный приход в `balance`, потому что эти деньги уже находились у магазина. Меняется только обязательство вернуть их.

## orders

Факт клиентской продажи.

Поля:

- `client_id`;
- `employee_id` — конкретный розничный исполнитель;
- `batch_id`;
- `product_id`;
- `quantity` — фасовка;
- `revenue`;
- `cost`;
- `employee_cost`;
- `employee_deposit_contribution`;
- `quality`;
- `status`;
- `created_at`.

Заказ создаётся только из `retail_positions`.

## reviews

Отзывы клиентов.

Поля:

- `order_id`;
- `client_id`;
- `product_id`;
- `employee_id`;
- `rating`;
- `text`;
- `quality_sentiment`;
- `delivery_sentiment`;
- `created_at`.

Фасовка берётся из `orders.quantity`.

## disputes

Связан с одним заказом.

Основные поля:

- `true_cause`;
- `message`;
- `evidence_json`;
- `courier_reply`;
- `decision`;
- `refund_amount`;
- `refund_source`;
- `refund_employee_id`;
- `deadline_at`;
- `status`;
- `resolved_at`.

## supplier_offers

Предложения поставщиков:

- товар;
- количество;
- unit cost;
- сигнал качества;
- срок;
- статус.

После выбора предложения игрок выбирает оптового сотрудника. Недостаточный депозит не запрещает покупку, а формирует `unsecured` и риск.

## candidates, recruitment_drafts, recruitment_campaigns

Найм хранит роль вакансии, рекламный канал и условия.

В draft/campaign фиксируются:

- `role`;
- ставка;
- минимальный депозит;
- процент отчислений;
- требования;
- объём и длительность рекламы.

После найма кандидат становится сотрудником выбранной роли.

## payroll_runs

История суточных выплат:

- `gross_wages`;
- `cash_paid`;
- `deposit_added`;
- `employee_count`;
- `status`;
- `created_at`.

## inbox

Типы клиентских сообщений:

- `dispute`;
- `discount_request`.

Кадровые:

- `raise_request`;
- `leave_request`;
- `advance_request`;
- `employee_exit` — в том числе срочная потеря сотрудника с товаром;
- `payroll_shortfall`;
- `payroll_report`.

В кадровом `payload_json` сохраняется `employee_id`, поэтому сообщение может вести прямо в профиль.

## ledger

Журнал фактических денежных движений и отдельных аудиторских событий.

Основные типы:

- `capital`;
- `sale`;
- `procurement`;
- `recruitment`;
- `salary`;
- `refund`;
- `refund_employee_deposit`;
- `deposit_in`;
- `deposit_out`;
- `employee_settlement`;
- `deposit_forfeit`.

`deposit_forfeit` может иметь `amount = 0`: удержание депозита не является новым cash-flow, а снимает обязательство магазина.

## analytics_events

Долговечный журнал действий игрока и игровых событий.

Основные поля:

- `player_id`;
- `run_id` — конкретное прохождение между reset-ами;
- `event_kind` — `player_action`, `game_event` или `system`;
- `event_name` — стабильное техническое название;
- `source` — подсистема;
- `entity_type`, `entity_id` — связанная игровая сущность;
- `balance` — snapshot денежного состояния;
- `rating` — snapshot рейтинга;
- `time_multiplier` — snapshot скорости;
- `payload_json` — параметры события;
- `created_at`.

Таблица не содержит FK на `shops`. Это принципиально: `/reset` должен очищать игровой state, но аналитическая история предыдущего прохождения должна сохраняться.

Перед удалением `shops` trigger пишет `progress_reset`. После создания нового магазина события относятся к новому `run_id`.

Player actions логируются middleware-слоем Telegram. Системные изменения вроде заказа, диспута, публикации позиций, найма и payroll в основном фиксируются SQLite-trigger-ами, поэтому фоновые события тоже попадают в журнал.

Подробнее: [ANALYTICS_EVENT_LOG.md](ANALYTICS_EVENT_LOG.md).

## Увольнение

При обычном увольнении сотрудник должен быть без товара, активной задачи и ожидающего назначения.

Магазин выплачивает:

`employee.deposit + employee.wages_accrued`

После этого сотрудник деактивируется, а его исторические заказы, отзывы и диспуты сохраняются до `/reset`. Их аналитические события остаются в `analytics_events` и после reset.

## Почему SQLite достаточно

MVP работает в одном процессе, использует WAL и короткие транзакции. Для текущего масштаба SQLite остаётся достаточным и удобным для аудита симуляции.

При нескольких воркерах или конкурентной записи следующим шагом будет PostgreSQL.
