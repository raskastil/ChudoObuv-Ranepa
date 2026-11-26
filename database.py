import pymysql
from pymysql.cursors import DictCursor


CLIENT, MANAGER, ADMIN = 1, 2, 3


class Database:
    def __init__(self, host, port, user, password):
        self.connection = pymysql.connect(
            host=host, port=port, user=user, password=password,
            database="chudo_obuv", charset="utf8mb4", cursorclass=DictCursor,
            autocommit=True, connect_timeout=5, read_timeout=10, write_timeout=10,
        )

    def rows(self, sql, args=()):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, args)
            return cursor.fetchall()

    def user(self, login):
        rows = self.rows(
            "SELECT id, role_id, CONCAT_WS(' ', last_name, first_name, patronymic) AS name "
            "FROM users WHERE login=%s", (login,),
        )
        return rows[0] if rows else None

    def catalog(self):
        return self.rows(
            "SELECT p.id, p.name, p.image_file, p.description, p.composition, p.price, "
            "c.name AS category, s.name AS subcategory, m.name AS manufacturer, "
            "(SELECT COALESCE(SUM(available_quantity), 0) FROM stock_items "
            "WHERE product_id=p.id) AS quantity "
            "FROM products p JOIN subcategories s ON p.subcategory_id=s.id "
            "JOIN categories c ON s.category_id=c.id "
            "JOIN manufacturers m ON p.manufacturer_id=m.id ORDER BY p.name"
        )

    def sizes(self, product_id):
        return self.rows(
            "SELECT si.id, s.size_value AS size, si.available_quantity AS quantity "
            "FROM stock_items si JOIN sizes s ON si.size_id=s.id "
            "WHERE si.product_id=%s ORDER BY s.size_value", (product_id,),
        )

    def customers(self):
        return self.rows(
            "SELECT id, CONCAT_WS(' ', last_name, first_name, patronymic) AS name "
            "FROM users ORDER BY name, id"
        )

    def orders(self, actor):
        self._require_staff(actor)
        return self.rows(
            "SELECT o.id, o.ordered_at, o.customer_id, o.total_amount, "
            "CONCAT_WS(' ', u.last_name, u.first_name, u.patronymic) AS customer "
            "FROM order_totals o JOIN users u ON o.customer_id=u.id "
            "ORDER BY o.ordered_at DESC, o.id DESC"
        )

    def order_items(self, actor, order_id):
        self._require_staff(actor)
        return self.rows(
            "SELECT oi.stock_item_id, p.name, s.size_value AS size, oi.quantity, "
            "oi.unit_price AS price FROM order_items oi "
            "JOIN stock_items si ON oi.stock_item_id=si.id "
            "JOIN products p ON si.product_id=p.id JOIN sizes s ON si.size_id=s.id "
            "WHERE oi.order_id=%s ORDER BY p.name, s.size_value", (order_id,),
        )

    @staticmethod
    def _require_staff(actor):
        if actor["role_id"] not in (MANAGER, ADMIN):
            raise ValueError("Просмотр и управление заказами доступны сотрудникам.")

    def save_order(self, actor, customer_id, quantities, order_id=None):
        if not quantities or any(not isinstance(qty, int) or qty <= 0 for qty in quantities.values()):
            raise ValueError("В заказе должна быть хотя бы одна позиция с количеством больше нуля.")
        if actor["role_id"] == CLIENT and customer_id != actor["id"]:
            raise ValueError("Можно оформить заказ только на своё имя.")
        if order_id is not None and actor["role_id"] != ADMIN:
            raise ValueError("Редактирование заказа доступно администратору.")
        return self._write_order(customer_id, quantities, order_id, delete=False)

    def delete_order(self, actor, order_id):
        self._require_staff(actor)
        self._write_order(None, {}, order_id, delete=True)

    def _write_order(self, customer_id, quantities, order_id, *, delete):
        self.connection.begin()
        try:
            with self.connection.cursor() as cur:
                previous = {}
                if order_id is not None:
                    cur.execute("SELECT id FROM orders WHERE id=%s FOR UPDATE", (order_id,))
                    if not cur.fetchone():
                        raise ValueError("Заказ уже удалён. Обновите список.")
                    cur.execute(
                        "SELECT stock_item_id, quantity, unit_price FROM order_items "
                        "WHERE order_id=%s", (order_id,),
                    )
                    previous = {row["stock_item_id"]: row for row in cur.fetchall()}

                # A consistent lock order lets concurrent orders share stock safely.
                prices = {}
                for item_id in sorted(previous.keys() | quantities.keys()):
                    cur.execute(
                        "SELECT si.available_quantity, p.price, p.name "
                        "FROM stock_items si JOIN products p ON p.id=si.product_id "
                        "WHERE si.id=%s FOR UPDATE", (item_id,),
                    )
                    stock = cur.fetchone()
                    if stock is None:
                        raise ValueError("Товарная позиция больше недоступна.")
                    old = previous.get(item_id)
                    change = quantities.get(item_id, 0) - (old["quantity"] if old else 0)
                    if change > stock["available_quantity"]:
                        raise ValueError(f"Недостаточно товара на складе: {stock['name']}.")
                    cur.execute(
                        "UPDATE stock_items SET available_quantity=available_quantity-%s WHERE id=%s",
                        (change, item_id),
                    )
                    prices[item_id] = old["unit_price"] if old else stock["price"]

                if delete:
                    cur.execute("DELETE FROM orders WHERE id=%s", (order_id,))
                else:
                    if order_id is None:
                        cur.execute("INSERT INTO orders (customer_id) VALUES (%s)", (customer_id,))
                        order_id = cur.lastrowid
                    else:
                        cur.execute("UPDATE orders SET customer_id=%s WHERE id=%s", (customer_id, order_id))
                        cur.execute("DELETE FROM order_items WHERE order_id=%s", (order_id,))
                    cur.executemany(
                        "INSERT INTO order_items (order_id, stock_item_id, quantity, unit_price) "
                        "VALUES (%s,%s,%s,%s)",
                        [(order_id, key, qty, prices[key]) for key, qty in quantities.items()],
                    )
            self.connection.commit()
            return order_id
        except Exception:
            self.connection.rollback()
            raise
