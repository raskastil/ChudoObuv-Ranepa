import argparse
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from pymysql import MySQLError

from database import ADMIN, CLIENT, Database


ASSETS = Path(__file__).resolve().parent / "assets"
TITLE = "Чудо Обувь"
ROLES = {CLIENT: "Клиент", 2: "Менеджер", ADMIN: "Администратор"}
ALL = "Все категории"
WHITE = "#FFFFFF"
INK = "#18352D"
MUTED = "#4B665D"
MINT = "#D2F6E7"
ACCENT = "#70B2AF"
EDGE = "#D7E6E0"
SURFACE = "#F3F9F6"


def money(amount):
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def size_label(size):
    return format(size.normalize(), "f")


def table(parent, columns):
    frame = ttk.Frame(parent)
    grid = ttk.Treeview(frame, columns=[col[0] for col in columns], show="headings", selectmode="browse")
    grid.tag_configure("stripe", background=SURFACE)
    for key, label, width in columns:
        grid.heading(key, text=label)
        grid.column(key, width=width, stretch=key in ("name", "customer"),
                    anchor="e" if key in ("price", "total", "quantity", "qty") else "w")
    scroll = ttk.Scrollbar(frame, command=grid.yview)
    grid.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    grid.pack(side="left", fill="both", expand=True)
    return frame, grid


class App:
    def __init__(self, root, db):
        self.root, self.db = root, db
        self.actor = None
        self.cart = {}
        self.editing = None
        self.edit_customer = None
        self.root.title(TITLE)
        self.root.geometry("1240x790")
        self.root.minsize(1080, 740)
        self.root.configure(background=WHITE)
        self.root.option_add("*Font", "Calibri 12")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", font=("Calibri", 12), foreground=INK)
        style.configure("TFrame", background=WHITE)
        style.configure("TLabel", background=WHITE, foreground=INK)
        style.configure("Header.TFrame", background=MINT)
        style.configure("Header.TLabel", background=MINT, foreground=INK)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Calibri", 24, "bold"))
        style.configure("Product.TLabel", font=("Calibri", 17, "bold"))
        style.configure("Price.TLabel", font=("Calibri", 17, "bold"), foreground="#21594E")
        style.configure("Chip.TLabel", background=MINT, foreground=INK, padding=(10, 4))
        style.configure("TButton", background=SURFACE, bordercolor=EDGE, lightcolor=SURFACE, darkcolor=SURFACE,
                        foreground=INK, padding=(13, 7), font=("Calibri", 12, "bold"), relief="flat")
        style.map("TButton", background=[("pressed", "#C9E8DC"), ("active", MINT)])
        style.configure("Accent.TButton", background=ACCENT, bordercolor=ACCENT, lightcolor=ACCENT,
                        darkcolor=ACCENT, foreground="#102523")
        style.map("Accent.TButton", background=[("disabled", SURFACE), ("pressed", "#5A9B98"), ("active", "#90C4C0")])
        style.configure("TEntry", padding=(7, 5), bordercolor=EDGE, fieldbackground=WHITE)
        style.configure("TCombobox", padding=(7, 5), bordercolor=EDGE, arrowsize=14)
        style.configure("TSpinbox", padding=(6, 5), bordercolor=EDGE, arrowsize=12)
        style.configure("Treeview", rowheight=35, background=WHITE, fieldbackground=WHITE,
                        bordercolor=EDGE, lightcolor=WHITE, darkcolor=WHITE)
        style.map("Treeview", background=[("selected", "#286457")], foreground=[("selected", WHITE)])
        style.configure("Treeview.Heading", font=("Calibri", 12, "bold"), padding=(8, 7),
                        background=MINT, foreground=INK, bordercolor=MINT, lightcolor=MINT, darkcolor=MINT)
        style.map("Treeview.Heading", background=[("active", "#BEECDD")])
        style.configure("TSeparator", background=EDGE)
        try:
            self.root.iconbitmap(default=str(ASSETS / "Чудо Обувь.ico"))
        except tk.TclError:
            pass

        header = ttk.Frame(root, padding=(24, 12), style="Header.TFrame")
        header.pack(fill="x")
        self.logo = self.image("Чудо Обувь.png", 110, 48)
        ttk.Label(header, image=self.logo, style="Header.TLabel").pack(side="left", padx=(0, 14))
        ttk.Label(header, text=TITLE, font=("Calibri", 22, "bold"), style="Header.TLabel").pack(side="left")
        self.login_button = ttk.Button(header, text="Войти", command=self.login)
        self.login_button.pack(side="right")
        self.identity = ttk.Label(header, text="Гость", style="Header.TLabel")
        self.identity.pack(side="right", padx=12)

        content = ttk.Frame(root, padding=(24, 16))
        content.pack(fill="both", expand=True)
        self.search = tk.StringVar()
        self.category = tk.StringVar(value=ALL)
        self.sorting = tk.StringVar(value="По названию")
        self.message = tk.StringVar(value="Выберите модель, чтобы посмотреть её размеры и остатки.")
        top = ttk.Frame(content)
        top.pack(fill="x", pady=(0, 12))
        ttk.Label(top, text="Каталог обуви", style="Title.TLabel", font=("Calibri", 24, "bold")).pack(side="left")
        self.catalog_count = ttk.Label(top, style="Chip.TLabel")
        self.catalog_count.pack(side="left", padx=14)
        self.actions = ttk.Frame(top)
        self.actions.pack(side="right")
        self.cart_button = ttk.Button(self.actions, text="Заказ (0)", style="Accent.TButton", command=self.show_cart)
        self.orders_button = ttk.Button(self.actions, text="Список заказов", command=self.show_orders)
        ttk.Button(self.actions, text="Обновить", command=lambda: self.run(self.refresh)).pack(side="right")

        self.filters = ttk.Frame(content)
        ttk.Label(self.filters, text="Поиск", style="Muted.TLabel").pack(side="left")
        ttk.Entry(self.filters, textvariable=self.search, width=24).pack(side="left", padx=(6, 12))
        self.categories = ttk.Combobox(self.filters, textvariable=self.category, state="readonly", width=21)
        self.categories.pack(side="left", padx=(0, 12))
        ttk.Combobox(
            self.filters, textvariable=self.sorting, state="readonly", width=19,
            values=("По названию", "Сначала дешевле", "Сначала дороже"),
        ).pack(side="left")
        for var in (self.search, self.category, self.sorting):
            var.trace_add("write", lambda *args: self.run(self.filter_products))

        self.body = ttk.Frame(content)
        self.body.pack(fill="both", expand=True)
        catalog, self.products_table = table(self.body, [
            ("name", "Модель", 350), ("category", "Подкатегория", 123), ("price", "Цена", 105),
            ("quantity", "Остаток", 75),
        ])
        details_border = tk.Frame(self.body, background=EDGE, borderwidth=0, padx=1, pady=1)
        details_border.pack(side="right", fill="y")
        details = ttk.Frame(details_border, padding=(16, 12), width=332)
        details.pack(fill="both", expand=True)
        catalog.pack(side="left", fill="both", expand=True, padx=(0, 18))
        self.products_table.tag_configure("low", background="#FF8080")
        self.products_table.bind("<<TreeviewSelect>>", lambda event: self.run(self.show_product))
        self.product_category = ttk.Label(details, style="Chip.TLabel")
        self.product_category.pack(anchor="w")
        self.photo = ttk.Label(details)
        self.photo.pack(anchor="center", pady=(4, 2))
        self.product_name = ttk.Label(details, wraplength=300, justify="left", style="Product.TLabel",
                                      font=("Calibri", 17, "bold"))
        self.product_name.pack(anchor="w", pady=(0, 3))
        self.product_price = ttk.Label(details, style="Price.TLabel", font=("Calibri", 17, "bold"))
        self.product_price.pack(anchor="w", pady=(0, 7))
        order_controls = ttk.Frame(details)
        order_controls.pack(side="bottom", fill="x")
        ttk.Separator(order_controls).pack(fill="x", pady=(0, 9))
        selectors = ttk.Frame(order_controls)
        selectors.pack(fill="x")
        self.size = ttk.Combobox(selectors, state="readonly", width=17)
        self.size.pack(side="left")
        self.quantity = ttk.Spinbox(selectors, from_=1, to=10000, width=5)
        self.quantity.set(1)
        self.quantity.pack(side="left", padx=6)
        self.add_button = ttk.Button(order_controls, text="Добавить в заказ", style="Accent.TButton",
                                     command=lambda: self.run(self.add_item))
        self.add_button.pack(fill="x", pady=(9, 0))
        description_area = ttk.Frame(details)
        description_area.pack(fill="both", expand=True, pady=(0, 8))
        self.details = tk.Text(description_area, width=38, height=6, wrap="word", background=WHITE,
                               foreground=MUTED, borderwidth=0, highlightthickness=0,
                               font=("Calibri", 11), padx=1, state="disabled")
        description_scroll = ttk.Scrollbar(description_area, command=self.details.yview)
        self.details.configure(yscrollcommand=description_scroll.set)
        description_scroll.pack(side="right", fill="y")
        self.details.pack(side="left", fill="both", expand=True)
        ttk.Label(content, textvariable=self.message, style="Muted.TLabel").pack(fill="x", pady=(11, 0))
        self.refresh()
        self.update_role()

    def run(self, callback):
        try:
            return callback()
        except (MySQLError, ValueError) as exc:
            messagebox.showerror(TITLE, str(exc), parent=self.root)

    def image(self, filename, max_width, max_height):
        try:
            source = tk.PhotoImage(file=ASSETS / Path(filename).name, master=self.root)
        except tk.TclError:
            source = tk.PhotoImage(file=ASSETS / "picture.png", master=self.root)
        factor = max(1, -(-source.width() // max_width), -(-source.height() // max_height))
        return source.subsample(factor)

    def refresh(self):
        self.products = {row["id"]: row for row in self.db.catalog()}
        self.categories.configure(values=(ALL, *sorted({p["category"] for p in self.products.values()})))
        self.filter_products()

    def filter_products(self):
        selected = self.products_table.selection()
        self.products_table.delete(*self.products_table.get_children())
        query = self.search.get().strip().casefold()
        category = self.category.get()
        rows = list(self.products.values())
        if self.actor and self.sorting.get() != "По названию":
            rows.sort(key=lambda row: row["price"], reverse=self.sorting.get() == "Сначала дороже")
        visible_count = 0
        for row in rows:
            searchable = " ".join(row[k] for k in ("name", "category", "subcategory", "manufacturer")).casefold()
            if self.actor and (query not in searchable or category not in (ALL, row["category"])):
                continue
            stripe = visible_count % 2 == 1
            self.products_table.insert("", "end", iid=row["id"], values=(
                row["name"], row["subcategory"], money(row["price"]), row["quantity"],
            ), tags=("low",) if row["quantity"] <= 3 else ("stripe",) if stripe else ())
            visible_count += 1
        choices = self.products_table.get_children()
        self.catalog_count.configure(text=f"Моделей: {len(choices)}")
        if choices:
            self.products_table.selection_set(selected[0] if selected and selected[0] in choices else choices[0])
        self.show_product()

    def show_product(self):
        selected = self.products_table.selection()
        self.selected = self.products.get(int(selected[0])) if selected else None
        self.stock = self.db.sizes(self.selected["id"]) if self.selected else ()
        self.photo_image = self.image(self.selected["image_file"] if self.selected else "picture.png", 300, 209)
        self.photo.configure(image=self.photo_image)
        self.product_category.configure(text=self.selected["category"] if self.selected else "Каталог")
        self.product_name.configure(text=self.selected["name"] if self.selected else "Поиск без результатов")
        self.product_price.configure(text=money(self.selected["price"]) if self.selected else "")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", (
            self.selected["description"] + "\n\n" + self.selected["composition"]
            if self.selected else "Измените запрос или категорию."
        ))
        self.details.configure(state="disabled")
        self.size.configure(values=[f"{size_label(s['size'])} / остаток {s['quantity']}" for s in self.stock])
        self.size.set("")
        if self.stock:
            self.size.current(0)
        self.add_button.configure(state="normal" if self.actor and self.stock else "disabled")

    def login(self):
        if self.actor:
            if self.cart and not messagebox.askyesno(TITLE, "Очистить черновик и выйти?", parent=self.root):
                return
            self.actor = None
            self.reset_cart()
        else:
            login = simpledialog.askstring("Вход", "Логин пользователя", parent=self.root)
            if not login:
                return
            actor = self.run(lambda: self.db.user(login.strip()))
            if not actor:
                self.message.set("Вход не выполнен. Проверьте логин.")
                return
            self.actor = actor
            self.message.set("Выберите модель, размер и количество.")
        self.update_role()
        self.run(self.refresh)

    def update_role(self):
        self.filters.pack_forget()
        self.cart_button.pack_forget()
        self.orders_button.pack_forget()
        self.login_button.configure(text="Выйти" if self.actor else "Войти")
        self.identity.configure(text=f"{self.actor['name']} · {ROLES[self.actor['role_id']]}" if self.actor else "Гость")
        if self.actor:
            self.filters.pack(fill="x", pady=(0, 12), before=self.body)
            self.cart_button.pack(side="left", padx=(0, 8))
            if self.actor["role_id"] != CLIENT:
                self.orders_button.pack(side="left", padx=(0, 8))
        self.add_button.configure(state="normal" if self.actor and self.stock else "disabled")

    def cart_badge(self):
        self.cart_button.configure(text=f"Заказ ({sum(item['quantity'] for item in self.cart.values())})")

    def reset_cart(self):
        self.cart.clear()
        self.editing = self.edit_customer = None
        self.cart_badge()

    def add_item(self):
        index = self.size.current()
        if index < 0 or not self.actor:
            return
        stock = self.stock[index]
        qty = int(self.quantity.get())
        current = self.cart.get(stock["id"], {})
        total_qty = qty + current.get("quantity", 0)
        if qty <= 0:
            raise ValueError("Введите количество больше нуля.")
        if self.editing is None and total_qty > stock["quantity"]:
            raise ValueError("Столько пар выбранного размера нет в наличии.")
        self.cart[stock["id"]] = {
            "name": self.selected["name"], "size": stock["size"],
            "price": current.get("price", self.selected["price"]), "quantity": total_qty,
        }
        self.cart_badge()
        self.message.set(f"Позиция добавлена: {self.selected['name']}, размер {size_label(stock['size'])}.")

    def dialog(self, title, dimensions):
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry(dimensions)
        window.transient(self.root)
        window.grab_set()
        panel = ttk.Frame(window, padding=(18, 12))
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text=title, style="Title.TLabel", font=("Calibri", 23, "bold")).pack(anchor="w", pady=(0, 10))
        return window, panel

    def show_cart(self):
        if not self.actor:
            return
        window, panel = self.dialog(f"Заказ № {self.editing}" if self.editing else "Новый заказ", "820x500")
        customers = ([self.actor] if self.actor["role_id"] == CLIENT else self.db.customers())
        ids = [row["id"] for row in customers]
        people = ttk.Combobox(panel, state="readonly", values=[row["name"] for row in customers])
        people.pack(fill="x", pady=(0, 8))
        people.current(ids.index(self.edit_customer or self.actor["id"]))
        controls = ttk.Frame(panel)
        controls.pack(side="bottom", fill="x")
        summary = ttk.Label(panel, anchor="e")
        summary.pack(side="bottom", fill="x", pady=8)
        frame, grid = table(panel, [
            ("name", "Модель", 340), ("size", "Размер", 80), ("qty", "Количество", 120), ("price", "Цена за пару", 125),
        ])
        frame.pack(fill="both", expand=True)

        def fill():
            grid.delete(*grid.get_children())
            for index, (key, row) in enumerate(self.cart.items()):
                grid.insert("", "end", iid=key, values=(row["name"], size_label(row["size"]), row["quantity"], money(row["price"])),
                            tags=("stripe",) if index % 2 else ())
            summary.configure(text="Итого: " + money(sum(row["price"] * row["quantity"] for row in self.cart.values())))
            self.cart_badge()

        def change(remove=False):
            selected = grid.selection()
            if not selected:
                return
            key = int(selected[0])
            if remove:
                del self.cart[key]
            else:
                quantity = simpledialog.askinteger("Количество", "Количество пар", minvalue=1,
                                                   maxvalue=10000, initialvalue=self.cart[key]["quantity"], parent=window)
                if quantity is not None:
                    self.cart[key]["quantity"] = quantity
            fill()

        def save():
            order_id = self.run(lambda: self.db.save_order(
                self.actor, ids[people.current()], {key: row["quantity"] for key, row in self.cart.items()}, self.editing,
            ))
            if order_id is not None:
                window.destroy()
                self.reset_cart()
                self.run(self.refresh)
                self.message.set(f"Заказ № {order_id} сохранён.")

        ttk.Button(controls, text="Изменить количество", command=change).pack(side="left", padx=(0, 7))
        ttk.Button(controls, text="Убрать позицию", command=lambda: change(True)).pack(side="left")
        ttk.Button(controls, text="Сохранить заказ", style="Accent.TButton", command=save).pack(side="right")
        if self.editing:
            def cancel():
                self.reset_cart()
                window.destroy()
            ttk.Button(controls, text="Отменить изменения", command=cancel).pack(side="right", padx=8)
        fill()

    def show_orders(self):
        if not self.actor or self.actor["role_id"] == CLIENT:
            return
        orders = self.run(lambda: self.db.orders(self.actor))
        if orders is None:
            return
        window, panel = self.dialog("Список заказов", "930x620")
        controls = ttk.Frame(panel)
        controls.pack(side="bottom", fill="x")
        frame, grid = table(panel, [
            ("id", "№", 65), ("date", "Дата", 160), ("customer", "ФИО клиента", 360),
            ("total", "Итого", 130),
        ])
        frame.pack(fill="both", expand=True)
        line_frame, lines = table(panel, [
            ("name", "Товарная позиция", 350), ("size", "Размер", 90), ("qty", "Количество", 120), ("price", "Цена за пару", 135),
        ])
        lines.configure(height=4)
        line_frame.pack(fill="x", pady=10)
        order_by_id = {order["id"]: order for order in orders}
        for index, order in enumerate(orders):
            grid.insert("", "end", iid=order["id"], values=(
                order["id"], order["ordered_at"].strftime("%d.%m.%Y %H:%M"),
                order["customer"], money(order["total_amount"]),
            ), tags=("stripe",) if index % 2 else ())

        def display():
            lines.delete(*lines.get_children())
            if grid.selection():
                items = self.run(lambda: self.db.order_items(self.actor, int(grid.selection()[0]))) or ()
                for item in items:
                    lines.insert("", "end", values=(item["name"], size_label(item["size"]), item["quantity"], money(item["price"])))

        def edit():
            if not grid.selection():
                return
            order_id = int(grid.selection()[0])
            if self.cart and not messagebox.askyesno(TITLE, "Заменить текущий черновик?", parent=window):
                return
            items = self.run(lambda: self.db.order_items(self.actor, order_id))
            if items is not None:
                self.cart = {row["stock_item_id"]: row for row in items}
                self.editing = order_id
                self.edit_customer = order_by_id[order_id]["customer_id"]
                self.cart_badge()
                window.destroy()
                self.show_cart()

        def delete():
            if not grid.selection():
                return
            order_id = int(grid.selection()[0])
            if messagebox.askyesno(TITLE, f"Удалить заказ № {order_id} и вернуть пары на склад?", parent=window):
                def perform():
                    self.db.delete_order(self.actor, order_id)
                    order_by_id.pop(order_id)
                    grid.delete(str(order_id))
                    if order_id == self.editing:
                        self.reset_cart()
                    display()
                    self.refresh()
                self.run(perform)

        grid.bind("<<TreeviewSelect>>", lambda event: display())
        if grid.get_children():
            grid.selection_set(grid.get_children()[0])
        ttk.Button(controls, text="Удалить заказ", command=delete).pack(side="left")
        if self.actor["role_id"] == ADMIN:
            ttk.Button(controls, text="Редактировать заказ", command=edit).pack(side="left", padx=8)
        ttk.Button(controls, text="Закрыть", command=window.destroy).pack(side="right")


def main():
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="root")
    args = parser.parse_args()
    root = tk.Tk()
    root.protocol("WM_DELETE_WINDOW", root.quit)
    root.withdraw()
    password = os.environ.get("CHUDO_DB_PASSWORD")
    if password is None:
        password = simpledialog.askstring("MySQL", f"Пароль MySQL для {args.user}", show="*", parent=root)
    if password is not None:
        try:
            db = Database(args.host, args.port, args.user, password)
            try:
                App(root, db)
                root.deiconify()
                root.mainloop()
            finally:
                db.connection.close()
        except MySQLError as exc:
            messagebox.showerror(TITLE, f"Проверьте подключение к MySQL и импорт chudo_obuv.sql.\n\n{exc}", parent=root)
    if root.winfo_exists():
        root.destroy()


if __name__ == "__main__":
    main()
