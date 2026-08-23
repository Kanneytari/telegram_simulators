# Модель данных SQLite

## Общая схема

```text
shops
 ├── settings
 ├── employees
 ├── candidates
 ├── recruitment_drafts
 ├── recruitment_campaigns
 ├── payroll_runs
 ├── clients
 ├── supplier_offers ── suppliers
 ├── batches ────────── suppliers + products
 ├── listings ───────── products
 ├── orders ─────────── clients + employees + batches + products
 │    └── disputes
 ├── inbox
 └── ledger
```

Все игровые сущности привязаны к `player_id`. Удаление `shops.player_id` каскадно удаляет прогресс конкретного игрока, поэтому `/reset` не затрагивает других пользователей.

## shops

Главное состояние магазина.

Основные поля:

- `balance` — фактический денежный остаток;
- `reserve_target` — целевой резерв;
- `rating` — клиентский рейтинг;
- `last_simulated_at` — последняя точка расчёта игрового времени;
- `total_revenue`, `total_profit`, `total_orders` — lifetime-метрики.

Свободные деньги не хранятся отдельным полем. Они рассчитываются динамически:

`balance - deposits - wages_accrued - reserve_target`

## settings

Персональные настройки игрока.

- `notifications_enabled`;
- `hardcore`;
- `auto_refund_limit`, `auto_partial_limit` — задел под делегирование;
- `time_multiplier` — индивидуальная скорость симуляции;
- `last_payroll_at` — последний реальный зарплатный расчёт.

`time_multiplier` влияет только на конкретного игрока. Payroll от него не зависит.

## employees

Содержит видимые операционные данные и скрытые свойства.

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
- `joined_at`;
- `available`, `active`.

Скрытые:

- `reliability`;
- `attention`;
- `honesty`;
- `loyalty`;
- `stress`.

`wages_accrued` — уже заработанная, но ещё не выплаченная сумма. Она является обязательством магазина.

`deposit_contribution_pct` по умолчанию равен 10. При payroll соответствующая доля начисленной зарплаты не выплачивается деньгами, а увеличивает депозит сотрудника.

## payroll_runs

История суточных выплат.

Каждая запись хранит:

- `gross_wages` — полное начисление;
- `cash_paid` — фактическая денежная выплата;
- `deposit_added` — сумма, переведённая в депозиты;
- `employee_count` — сколько сотрудников попало в расчёт;
- `status`;
- `created_at`.

Таблица используется для 7-дневной зарплатной аналитики.

## candidates

Кандидат хранит скрытые характеристики будущего сотрудника и параметры конкретного объявления, на которое он откликнулся.

Дополнительные поля:

- `campaign_id`;
- `source_channel`;
- `offered_pay`;
- `min_deposit`;
- `deposit_contribution_pct`;
- `experience_level`.

После найма скрытые характеристики переносятся в `employees` без повторной генерации.

## recruitment_drafts

Текущая форма настройки вакансии игрока.

Хранит:

- канал;
- множитель рекламного охвата;
- длительность;
- ставку;
- минимальный депозит;
- процент отчислений;
- требование автомобиля;
- требование опыта.

Это позволяет полностью собирать кампанию через inline-кнопки и не терять настройки между сообщениями.

## recruitment_campaigns

Запущенные рекламные размещения.

Поля:

- `channel`;
- `cost`;
- `traffic_multiplier`;
- `duration_hours`;
- условия вакансии на момент запуска;
- `expected_min`, `expected_max`;
- `resolves_at`;
- `candidates_created`;
- `status`.

Условия копируются из draft в campaign как snapshot. Изменение новой вакансии не меняет уже оплаченный набор.

## clients

Наблюдаемая история:

- возраст аккаунта;
- число покупок на площадке;
- покупки в магазине;
- total spend;
- диспуты;
- выигранные диспуты.

Скрытые параметры:

- `fraud_propensity`;
- `patience`;
- `loyalty`;
- `review_tendency`.

## products

Глобальный справочник игровых товаров.

- `base_market_price`;
- `base_demand`;
- `complaint_modifier`.

## suppliers

Глобальный справочник поставщиков.

- `price_modifier`;
- `quality_mean`;
- `quality_sigma`;
- `reliability`.

## supplier_offers

Временные коммерческие предложения конкретного игрока.

- поставщик;
- товар;
- количество;
- unit cost;
- сигнал качества;
- срок действия;
- статус.

## batches

Каждая закупка остаётся отдельной сущностью.

- `quantity`;
- `remaining`;
- `unit_cost`;
- скрытое `quality`;
- поставщик;
- товар.

Это позволяет анализировать проблемность конкретных партий.

## listings

Комбинация товара и размера позиции.

Уникальный ключ:

`player_id + product_id + pack_size`

Цена меняется отдельно для каждой позиции.

## orders

Факт продажи и snapshot экономики заказа.

- `revenue`;
- `cost`;
- `employee_cost`;
- `employee_deposit_contribution` — ожидаемая доля ставки, которая при payroll уйдёт в депозит;
- `quality`;
- `quantity`.

`employee_cost` уменьшает прибыль сразу, даже если зарплата физически будет выплачена позже.

## disputes

Связан с одним заказом.

- `true_cause` — скрытая причина;
- `message`;
- `evidence_json`;
- `courier_reply`;
- `deadline_at`;
- `decision`;
- `status`.

## inbox

Универсальная очередь игровых взаимодействий.

Клиентские типы:

- `dispute`;
- `discount_request`.

Кадровые типы:

- `raise_request`;
- `leave_request`;
- `advance_request`;
- `employee_exit`;
- `payroll_shortfall`;
- `payroll_report`.

Прочие:

- `recruitment_result`;
- `tutorial`.

Кадровые сообщения выводятся в отдельной вкладке `Входящие → Сотрудники`. В `payload_json` хранится `employee_id`, поэтому из сообщения можно открыть профиль сотрудника.

Для запроса повышения в `payload_json` дополнительно хранятся:

- `requested_pay`;
- `offer_pay`;
- `floor_pay` — скрытая минимально приемлемая ставка;
- `round` — номер раунда переговоров.

## ledger

Журнал фактических денежных движений, а не бухгалтерская прибыль.

Основные типы:

- `capital`;
- `sale`;
- `refund`;
- `procurement`;
- `recruitment`;
- `salary`;
- `deposit_in`;
- `deposit_out`;
- `employee_loss`.

Зарплата появляется в ledger только в момент реальной суточной выплаты. До этого она существует как `wages_accrued`.

## Почему SQLite достаточно

MVP работает в одном процессе, использует WAL и короткие транзакции. Для текущего масштаба SQLite даёт простую диагностику и прозрачный аудит состояния.

Если появятся несколько воркеров, тяжёлая очередь фоновых задач или отдельная веб-панель с конкурентной записью, следующей точкой миграции будет PostgreSQL.
