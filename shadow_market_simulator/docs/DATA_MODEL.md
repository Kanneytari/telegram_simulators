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
 ├── batches ────────── suppliers + products + responsible employee
 ├── listings ───────── products
 ├── orders ─────────── clients + retail employees + batches + products
 │    ├── disputes
 │    └── reviews
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

Свободные деньги рассчитываются динамически:

`balance - deposits - wages_accrued - reserve_target`

Стартовые депозиты команды добавляются на баланс как деньги, которые магазин фактически держит, но одновременно учитываются как обязательство.

## settings

Персональные настройки игрока.

- `notifications_enabled`;
- `hardcore`;
- `auto_refund_limit`, `auto_partial_limit`;
- `time_multiplier` — индивидуальная скорость симуляции;
- `last_payroll_at` — последний реальный зарплатный расчёт.

Payroll не ускоряется `time_multiplier`.

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

Роли:

- `courier` — розничный сотрудник, связанный с клиентскими заказами;
- `warehouse` — оптовый сотрудник, отвечающий за партии.

Стандартное отчисление из заработка в депозит — 10%.

## batches

Каждая закупка остаётся отдельной сущностью.

Поля:

- `quantity`;
- `remaining`;
- `unit_cost`;
- скрытое `quality`;
- `supplier_id`;
- `product_id`;
- `responsible_employee_id` — оптовый сотрудник, отвечающий за остаток партии.

Стоимость товара на ответственности сотрудника:

`SUM(remaining × unit_cost)`

Свободное покрытие:

`employee.deposit - exposure`

Новую партию нельзя назначить сотруднику, если её стоимость превышает свободное покрытие.

## supplier_offers

Временные предложения конкретного игрока.

- поставщик;
- товар;
- количество;
- unit cost;
- сигнал качества;
- срок действия;
- статус.

При подтверждении покупки теперь дополнительно выбирается `responsible_employee_id`.

## orders

Факт продажи и snapshot экономики заказа.

- `client_id`;
- `employee_id` — розничный исполнитель;
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

Связка `order → employee` позволяет анализировать качество работы конкретного розничного сотрудника.

## reviews

Отдельная сущность клиентского отзыва.

Поля:

- `order_id` — уникальная связь с заказом;
- `client_id`;
- `product_id`;
- `employee_id`;
- `rating` — 1–5;
- `text`;
- `quality_sentiment` — `good`, `neutral`, `bad`;
- `delivery_sentiment` — `good`, `neutral`, `bad`;
- `created_at`.

Фасовка берётся через `orders.quantity`.

Один и тот же отзыв можно показать:

- в карточке товара;
- в профиле сотрудника;
- в агрегированной аналитике.

## disputes

Связан с одним заказом.

- `true_cause` — скрытая причина;
- `message`;
- `evidence_json`;
- `courier_reply`;
- `deadline_at`;
- `decision`;
- `refund_amount`;
- `refund_source` — `shop`, `employee`, `none`;
- `refund_employee_id`;
- `status`;
- `resolved_at`.

После завершённого диспута отзыв может учитывать как исходную проблему, так и решение магазина.

## candidates

Кандидат хранит скрытые характеристики будущего сотрудника и snapshot условий объявления.

Основные дополнительные поля:

- `role` — розница или опт;
- `campaign_id`;
- `source_channel`;
- `offered_pay`;
- `min_deposit`;
- `deposit_contribution_pct`;
- `experience_level`.

После найма роль и характеристики переносятся в `employees`.

## recruitment_drafts

Текущая форма настройки вакансии.

Хранит:

- `role`;
- канал;
- множитель рекламного охвата;
- длительность;
- ставку;
- минимальный депозит;
- процент отчислений;
- требование автомобиля;
- требование опыта.

## recruitment_campaigns

Запущенные размещения.

Условия вакансии сохраняются snapshot-ом на момент оплаты, включая `role`. Изменение draft после запуска не меняет уже оплаченную кампанию.

## payroll_runs

История суточных выплат.

- `gross_wages`;
- `cash_paid`;
- `deposit_added`;
- `employee_count`;
- `status`;
- `created_at`.

## clients

Наблюдаемая история:

- возраст аккаунта;
- число покупок;
- покупки в магазине;
- total spend;
- диспуты;
- выигранные диспуты.

Скрытые параметры:

- `fraud_propensity`;
- `patience`;
- `loyalty`;
- `review_tendency`.

`review_tendency` влияет на вероятность появления обычного отзыва.

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

## listings

Комбинация товара и фасовки.

Уникальный ключ:

`player_id + product_id + pack_size`

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

В кадровом `payload_json` хранится `employee_id`, поэтому сообщение может вести в профиль сотрудника.

## ledger

Журнал фактических денежных движений.

Основные типы:

- `capital`;
- `sale`;
- `refund`;
- `refund_employee_deposit`;
- `procurement`;
- `recruitment`;
- `salary`;
- `deposit_in`;
- `deposit_out`;
- `employee_settlement`;
- `employee_loss`.

## Почему SQLite достаточно

MVP работает в одном процессе, использует WAL и короткие транзакции. Для текущего масштаба SQLite даёт прозрачный аудит состояния.

При переходе к нескольким воркерам или конкурентной записи логичной следующей точкой миграции станет PostgreSQL.
