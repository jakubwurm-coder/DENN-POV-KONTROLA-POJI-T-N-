from __future__ import annotations

import subprocess
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

from allianz import load_allianz_vehicles
from compare import compare_vehicles
from config import load_config
from report import (
    prepare_output,
    write_comparison,
    write_duplicates,
    write_tirbazar_snapshot,
)
from tirbazar import load_tirbazar_vehicles
from uniqa import load_uniqa_vehicles


BG = "#061827"
HEADER_BG = "#082238"

PANEL = "#0A2A43"
BORDER = "#1B5276"

TEXT = "#FFFFFF"
TEXT_MUTED = "#9EB7CA"

ACCENT = "#54C8FF"

GREEN_BG = "#0D4938"
GREEN_FG = "#7AF0B5"

RED_BG = "#5A2028"
RED_FG = "#FF919B"

PURPLE_BG = "#572442"
PURPLE_FG = "#FF9FD2"

ORANGE_BG = "#594115"
ORANGE_FG = "#FFD166"

BLUE_BG = "#123E62"
BLUE_FG = "#7BD0FF"

ACTIVE_BG = "#17364A"
ACTIVE_FG = "#8DD8FF"

GRAY_BG = "#35404A"
GRAY_FG = "#D7DDE2"

ALLIANZ_BG = "#233B67"
ALLIANZ_FG = "#A8C7FF"

DEPOSIT_BG = "#33411C"
DEPOSIT_FG = "#D7F77A"


STATUS_COLORS = {
    "OK": (
        GREEN_BG,
        GREEN_FG,
    ),
    "CHYBÍ V UNIQA": (
        RED_BG,
        RED_FG,
    ),
    "NEPOJIŠTĚNO, ALE DEPOZIT": (
        DEPOSIT_BG,
        DEPOSIT_FG,
    ),
    "PRODANÉ, ALE V UNIQA": (
        PURPLE_BG,
        PURPLE_FG,
    ),
    "SPZ NESOUHLASÍ": (
        ORANGE_BG,
        ORANGE_FG,
    ),
    "NAVÍC V UNIQA": (
        BLUE_BG,
        BLUE_FG,
    ),
    "NELZE OVĚŘIT": (
        GRAY_BG,
        GRAY_FG,
    ),
}


class InsuranceCheckerApp(tk.Tk):

    def __init__(self):

        super().__init__()

        self.title(
            "Kontrola pojištění vozidel"
        )

        self.geometry(
            "1680x1000"
        )

        self.minsize(
            1280,
            820,
        )

        self.configure(
            bg=BG
        )

        self.results = []

        self.active_count = 0
        self.ok_uniqa = 0
        self.ok_allianz = 0
        self.ok_total = 0

        self.last_csv: Path | None = None

        self.search_var = tk.StringVar()

        self.filter_var = tk.StringVar(
            value="VŠE"
        )

        self._setup_style()
        self._build_gui()


    # ========================================================
    # STYLE
    # ========================================================

    def _setup_style(self):

        style = ttk.Style(self)

        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(
            "Checker.Treeview",
            background=PANEL,
            fieldbackground=PANEL,
            foreground=TEXT,
            rowheight=39,
            borderwidth=0,
            relief="flat",
            font=(
                "Helvetica",
                10,
            ),
        )

        style.configure(
            "Checker.Treeview.Heading",
            background=HEADER_BG,
            foreground=TEXT,
            font=(
                "Helvetica",
                10,
                "bold",
            ),
            relief="flat",
        )

        style.map(
            "Checker.Treeview",
            background=[
                (
                    "selected",
                    BORDER,
                )
            ],
            foreground=[
                (
                    "selected",
                    TEXT,
                )
            ],
        )


    # ========================================================
    # BUILD GUI
    # ========================================================

    def _build_gui(self):

        root = tk.Frame(
            self,
            bg=BG,
        )

        root.pack(
            fill="both",
            expand=True,
        )

        self._build_header(root)
        self._build_info(root)
        self._build_sources(root)
        self._build_toolbar(root)
        self._build_cards(root)
        self._build_table(root)
        self._build_footer(root)


    # ========================================================
    # HEADER
    # ========================================================

    def _build_header(
        self,
        parent,
    ):

        header = tk.Frame(
            parent,
            bg=HEADER_BG,
            padx=28,
            pady=18,
        )

        header.pack(
            fill="x"
        )

        left = tk.Frame(
            header,
            bg=HEADER_BG,
        )

        left.pack(
            side="left"
        )

        tk.Label(
            left,
            text="KONTROLA POJIŠTĚNÍ",
            bg=HEADER_BG,
            fg=TEXT,
            font=(
                "Helvetica",
                25,
                "bold",
            ),
        ).pack(
            anchor="w"
        )

        tk.Label(
            left,
            text="TIRBazar  →  UNIQA  →  Allianz  →  Depozit",
            bg=HEADER_BG,
            fg=TEXT_MUTED,
            font=(
                "Helvetica",
                11,
            ),
        ).pack(
            anchor="w",
            pady=(
                3,
                0,
            ),
        )

        right = tk.Frame(
            header,
            bg=HEADER_BG,
        )

        right.pack(
            side="right"
        )

        self.live_dot = tk.Label(
            right,
            text="●",
            bg=HEADER_BG,
            fg=GRAY_FG,
            font=(
                "Helvetica",
                14,
                "bold",
            ),
        )

        self.live_dot.pack(
            side="left",
            padx=(
                0,
                7,
            ),
        )

        self.live_status = tk.Label(
            right,
            text="PŘIPRAVENO",
            bg=HEADER_BG,
            fg=TEXT_MUTED,
            font=(
                "Helvetica",
                10,
                "bold",
            ),
        )

        self.live_status.pack(
            side="left"
        )


    # ========================================================
    # INFO
    # ========================================================

    def _build_info(
        self,
        parent,
    ):

        info = tk.Frame(
            parent,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=16,
            pady=10,
        )

        info.pack(
            fill="x",
            padx=28,
            pady=(
                14,
                10,
            ),
        )

        tk.Label(
            info,
            text="LOGIKA KONTROLY",
            bg=PANEL,
            fg=ACCENT,
            font=(
                "Helvetica",
                10,
                "bold",
            ),
        ).pack(
            anchor="w"
        )

        tk.Label(
            info,
            text=(
                "Aktivní vozidlo je v pořádku, pokud je pojištěné v UNIQA nebo Allianz. "
                "Pokud není v žádné pojišťovně, kontroluje se poznámka TIRBazar. "
                "Obsahuje-li text DEPOZIT, zobrazí se jako NEPOJIŠTĚNO, ALE DEPOZIT."
            ),
            bg=PANEL,
            fg=TEXT,
            font=(
                "Helvetica",
                10,
            ),
            justify="left",
        ).pack(
            anchor="w",
            pady=(
                4,
                2,
            ),
        )

        tk.Label(
            info,
            text=(
                "VIN = hlavní identifikátor  •  "
                "SPZ = sekundární identifikátor  •  "
                "TIRBazar = pouze čtení  •  "
                "výkup nebo výkup z komise"
            ),
            bg=PANEL,
            fg=TEXT_MUTED,
            font=(
                "Helvetica",
                9,
            ),
        ).pack(
            anchor="w"
        )


    # ========================================================
    # SOURCES
    # ========================================================

    def _build_sources(
        self,
        parent,
    ):

        sources = tk.Frame(
            parent,
            bg=BG,
        )

        sources.pack(
            fill="x",
            padx=24,
            pady=(
                0,
                10,
            ),
        )

        (
            self.tir_dot,
            self.tir_status,
            self.tir_detail,
        ) = self._source_box(
            sources,
            "TIRBAZAR DB",
            "SQL Server / pouze čtení",
        )

        (
            self.uniqa_dot,
            self.uniqa_status,
            self.uniqa_detail,
        ) = self._source_box(
            sources,
            "UNIQA",
            "AIV / Denní POV / Aktivní",
        )

        (
            self.allianz_dot,
            self.allianz_status,
            self.allianz_detail,
        ) = self._source_box(
            sources,
            "ALLIANZ",
            "Flotilové PDF",
        )


    def _source_box(
        self,
        parent,
        title,
        detail,
    ):

        box = tk.Frame(
            parent,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=14,
            pady=9,
        )

        box.pack(
            side="left",
            fill="x",
            expand=True,
            padx=4,
        )

        top = tk.Frame(
            box,
            bg=PANEL,
        )

        top.pack(
            fill="x"
        )

        dot = tk.Label(
            top,
            text="●",
            bg=PANEL,
            fg=GRAY_FG,
            font=(
                "Helvetica",
                11,
                "bold",
            ),
        )

        dot.pack(
            side="left",
            padx=(
                0,
                5,
            ),
        )

        tk.Label(
            top,
            text=title,
            bg=PANEL,
            fg=ACCENT,
            font=(
                "Helvetica",
                9,
                "bold",
            ),
        ).pack(
            side="left"
        )

        status = tk.Label(
            box,
            text="Zatím nenačteno",
            bg=PANEL,
            fg=TEXT_MUTED,
            font=(
                "Helvetica",
                10,
            ),
        )

        status.pack(
            anchor="w",
            pady=(
                4,
                0,
            ),
        )

        detail_label = tk.Label(
            box,
            text=detail,
            bg=PANEL,
            fg=TEXT_MUTED,
            font=(
                "Helvetica",
                8,
            ),
        )

        detail_label.pack(
            anchor="w",
            pady=(
                2,
                0,
            ),
        )

        return (
            dot,
            status,
            detail_label,
        )


    # ========================================================
    # TOOLBAR
    # ========================================================

    def _build_toolbar(
        self,
        parent,
    ):

        toolbar = tk.Frame(
            parent,
            bg=BG,
        )

        toolbar.pack(
            fill="x",
            padx=28,
            pady=(
                0,
                10,
            ),
        )

        self.run_button = tk.Button(
            toolbar,
            text="▶  SPUSTIT KONTROLU",
            command=self.run_check,
            bg=ACCENT,
            fg="#04131F",
            relief="flat",
            bd=0,
            font=(
                "Helvetica",
                10,
                "bold",
            ),
            padx=16,
            pady=9,
            cursor="pointinghand",
        )

        self.run_button.pack(
            side="left"
        )

        tk.Button(
            toolbar,
            text="Otevřít CSV",
            command=self.open_csv,
            bg=PANEL,
            fg=TEXT,
            relief="flat",
            bd=0,
            padx=13,
            pady=9,
            cursor="pointinghand",
        ).pack(
            side="left",
            padx=(
                8,
                4,
            ),
        )

        tk.Button(
            toolbar,
            text="Výstupy",
            command=self.open_output_folder,
            bg=PANEL,
            fg=TEXT,
            relief="flat",
            bd=0,
            padx=13,
            pady=9,
            cursor="pointinghand",
        ).pack(
            side="left",
            padx=4,
        )

        search_frame = tk.Frame(
            toolbar,
            bg=BG,
        )

        search_frame.pack(
            side="right"
        )

        tk.Label(
            search_frame,
            text="VIN / SPZ:",
            bg=BG,
            fg=TEXT_MUTED,
        ).pack(
            side="left",
            padx=(
                0,
                6,
            ),
        )

        entry = tk.Entry(
            search_frame,
            textvariable=self.search_var,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=25,
            font=(
                "Helvetica",
                11,
            ),
        )

        entry.pack(
            side="left",
            ipady=7,
        )

        self.search_var.trace_add(
            "write",
            lambda *_: self.fill_table(),
        )

        tk.Button(
            search_frame,
            text="Vše",
            command=self.clear_filter,
            bg=PANEL,
            fg=TEXT,
            relief="flat",
            bd=0,
            padx=12,
            pady=7,
            cursor="pointinghand",
        ).pack(
            side="left",
            padx=(
                8,
                0,
            ),
        )


    # ========================================================
    # CARDS
    # ========================================================

    def _build_cards(
        self,
        parent,
    ):

        outer = tk.Frame(
            parent,
            bg=BG,
        )

        outer.pack(
            fill="x",
            padx=24,
            pady=(
                0,
                10,
            ),
        )

        row1 = tk.Frame(
            outer,
            bg=BG,
        )

        row1.pack(
            fill="x"
        )

        row2 = tk.Frame(
            outer,
            bg=BG,
        )

        row2.pack(
            fill="x",
            pady=(
                7,
                0,
            ),
        )

        self.cards = {}

        row1_cards = [
            (
                "ACTIVE",
                "AKTIVNÍ KE KONTROLE",
                ACTIVE_BG,
                ACTIVE_FG,
            ),
            (
                "OK_TOTAL",
                "OK CELKEM",
                GREEN_BG,
                GREEN_FG,
            ),
            (
                "OK_UNIQA",
                "OK – UNIQA",
                GREEN_BG,
                GREEN_FG,
            ),
            (
                "OK_ALLIANZ",
                "OK – ALLIANZ",
                ALLIANZ_BG,
                ALLIANZ_FG,
            ),
        ]

        row2_cards = [
            (
                "MISSING",
                "CHYBÍ POJIŠTĚNÍ",
                RED_BG,
                RED_FG,
            ),
            (
                "DEPOSIT",
                "NEPOJIŠTĚNO, ALE DEPOZIT",
                DEPOSIT_BG,
                DEPOSIT_FG,
            ),
            (
                "SOLD_UNIQA",
                "PRODANÉ, ALE V UNIQA",
                PURPLE_BG,
                PURPLE_FG,
            ),
            (
                "EXTRA_UNIQA",
                "NAVÍC V UNIQA",
                BLUE_BG,
                BLUE_FG,
            ),
        ]

        for definition in row1_cards:

            self._make_card(
                row1,
                *definition,
            )

        for definition in row2_cards:

            self._make_card(
                row2,
                *definition,
            )


    def _make_card(
        self,
        parent,
        key,
        title,
        bg,
        fg,
    ):

        card = tk.Frame(
            parent,
            bg=bg,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=14,
            pady=10,
            cursor="pointinghand",
        )

        card.pack(
            side="left",
            fill="x",
            expand=True,
            padx=4,
        )

        title_label = tk.Label(
            card,
            text=title,
            bg=bg,
            fg=fg,
            font=(
                "Helvetica",
                9,
                "bold",
            ),
            cursor="pointinghand",
        )

        title_label.pack(
            anchor="w"
        )

        value_label = tk.Label(
            card,
            text="0",
            bg=bg,
            fg=fg,
            font=(
                "Helvetica",
                25,
                "bold",
            ),
            cursor="pointinghand",
        )

        value_label.pack(
            anchor="w",
            pady=(
                3,
                0,
            ),
        )

        self.cards[
            key
        ] = value_label

        for widget in (
            card,
            title_label,
            value_label,
        ):

            widget.bind(
                "<Button-1>",
                lambda event, k=key: self.card_filter(k),
            )


    # ========================================================
    # TABLE
    # ========================================================

    def _build_table(
        self,
        parent,
    ):

        table_frame = tk.Frame(
            parent,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        table_frame.pack(
            fill="both",
            expand=True,
            padx=28,
            pady=(
                0,
                10,
            ),
        )

        columns = (
            "status",
            "pojistovna",
            "vin",
            "spz_tir",
            "spz_uniqa",
            "vykup",
            "prodej",
            "detail",
        )

        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            style="Checker.Treeview",
        )

        headers = {
            "status": "STATUS",
            "pojistovna": "POJIŠŤOVNA",
            "vin": "VIN",
            "spz_tir": "SPZ TIRBAZAR",
            "spz_uniqa": "SPZ UNIQA",
            "vykup": "DATUM VÝKUPU",
            "prodej": "DATUM PRODEJE",
            "detail": "VÝSLEDEK",
        }

        for column, title in headers.items():

            self.tree.heading(
                column,
                text=title,
                anchor="w",
            )

        self.tree.column(
            "status",
            width=205,
        )

        self.tree.column(
            "pojistovna",
            width=105,
        )

        self.tree.column(
            "vin",
            width=195,
        )

        self.tree.column(
            "spz_tir",
            width=115,
        )

        self.tree.column(
            "spz_uniqa",
            width=105,
        )

        self.tree.column(
            "vykup",
            width=125,
        )

        self.tree.column(
            "prodej",
            width=125,
        )

        self.tree.column(
            "detail",
            width=620,
        )

        sy = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.tree.yview,
        )

        sx = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.tree.xview,
        )

        self.tree.configure(
            yscrollcommand=sy.set,
            xscrollcommand=sx.set,
        )

        self.tree.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        sy.grid(
            row=0,
            column=1,
            sticky="ns",
        )

        sx.grid(
            row=1,
            column=0,
            sticky="ew",
        )

        table_frame.grid_rowconfigure(
            0,
            weight=1,
        )

        table_frame.grid_columnconfigure(
            0,
            weight=1,
        )

        for status, colors in STATUS_COLORS.items():

            bg, fg = colors

            self.tree.tag_configure(
                status,
                background=bg,
                foreground=fg,
            )

        self.tree.bind(
            "<Double-1>",
            self.open_detail,
        )


    # ========================================================
    # FOOTER
    # ========================================================

    def _build_footer(
        self,
        parent,
    ):

        footer = tk.Frame(
            parent,
            bg=BG,
        )

        footer.pack(
            fill="x",
            padx=28,
            pady=(
                0,
                12,
            ),
        )

        self.footer_left = tk.Label(
            footer,
            text="Připraveno",
            bg=BG,
            fg=TEXT_MUTED,
            font=(
                "Helvetica",
                9,
            ),
        )

        self.footer_left.pack(
            side="left"
        )

        self.footer_right = tk.Label(
            footer,
            text="",
            bg=BG,
            fg=ACCENT,
            font=(
                "Helvetica",
                9,
                "bold",
            ),
        )

        self.footer_right.pack(
            side="right"
        )


    # ========================================================
    # RUN
    # ========================================================

    def run_check(self):

        self.run_button.config(
            state="disabled",
            text="Probíhá kontrola...",
        )

        self.live_dot.config(
            fg=ORANGE_FG,
        )

        self.live_status.config(
            text="KONTROLA PROBÍHÁ",
            fg=ORANGE_FG,
        )

        self.tir_dot.config(
            fg=ORANGE_FG,
        )

        self.tir_status.config(
            text="Načítám...",
            fg=ORANGE_FG,
        )

        self.uniqa_dot.config(
            fg=GRAY_FG,
        )

        self.uniqa_status.config(
            text="Čekám...",
            fg=TEXT_MUTED,
        )

        self.allianz_dot.config(
            fg=GRAY_FG,
        )

        self.allianz_status.config(
            text="Čekám...",
            fg=TEXT_MUTED,
        )

        threading.Thread(
            target=self._run_thread,
            daemon=True,
        ).start()


    def _run_thread(self):

        try:

            config = load_config()

            vehicles, duplicates = load_tirbazar_vehicles(
                config
            )

            self.active_count = sum(
                1
                for vehicle in vehicles
                if not vehicle.datum_prodeje
            )

            tir_time = datetime.now().strftime(
                "%d.%m.%Y %H:%M:%S"
            )

            self.after(
                0,
                self._tir_loaded,
                tir_time,
            )

            self.after(
                0,
                self._uniqa_loading,
            )

            uniqa = load_uniqa_vehicles()

            uniqa_time = datetime.now().strftime(
                "%d.%m.%Y %H:%M:%S"
            )

            self.after(
                0,
                self._uniqa_loaded,
                uniqa,
                uniqa_time,
            )

            self.after(
                0,
                self._allianz_loading,
            )

            allianz = load_allianz_vehicles()

            allianz_time = datetime.now().strftime(
                "%d.%m.%Y %H:%M:%S"
            )

            self.after(
                0,
                self._allianz_loaded,
                allianz,
                allianz_time,
            )

            results = compare_vehicles(
                tir=vehicles,
                uniqa=uniqa.vehicles,
                uniqa_available=uniqa.available,
                uniqa_error=uniqa.error,
                allianz=allianz.vehicles,
                allianz_available=allianz.available,
                allianz_error=allianz.error,
            )

            base = prepare_output()

            try:

                write_tirbazar_snapshot(
                    vehicles,
                    base,
                )

            except TypeError:

                active = [
                    vehicle
                    for vehicle in vehicles
                    if not vehicle.datum_prodeje
                ]

                sold = [
                    vehicle
                    for vehicle in vehicles
                    if vehicle.datum_prodeje
                ]

                write_tirbazar_snapshot(
                    active,
                    sold,
                    base,
                )

            write_duplicates(
                duplicates,
                base,
            )

            csv_path = write_comparison(
                results,
                base,
            )

            self.results = results
            self.last_csv = csv_path

            self.after(
                0,
                self._finish,
                uniqa,
                allianz,
            )

        except Exception as exc:

            self.after(
                0,
                self._show_error,
                str(exc),
            )


    # ========================================================
    # SOURCE STATUS
    # ========================================================

    def _tir_loaded(
        self,
        when,
    ):

        self.tir_dot.config(
            fg=GREEN_FG,
        )

        self.tir_status.config(
            text=f"Načteno: {when}",
            fg=GREEN_FG,
        )

        self.tir_detail.config(
            text=(
                f"SQL Server • Aktivních ke kontrole: "
                f"{self.active_count}"
            )
        )


    def _uniqa_loading(self):

        self.uniqa_dot.config(
            fg=ORANGE_FG,
        )

        self.uniqa_status.config(
            text="Načítám UNIQA...",
            fg=ORANGE_FG,
        )


    def _uniqa_loaded(
        self,
        uniqa,
        when,
    ):

        if uniqa.available:

            duplicate_count = len(
                getattr(
                    uniqa,
                    "duplicates",
                    [],
                )
            )

            self.uniqa_dot.config(
                fg=GREEN_FG,
            )

            self.uniqa_status.config(
                text=f"Načteno: {when}",
                fg=GREEN_FG,
            )

            self.uniqa_detail.config(
                text=(
                    f"Aktivních VIN: {len(uniqa.vehicles)}"
                    f" • Duplicitních VIN: {duplicate_count}"
                )
            )

        else:

            self.uniqa_dot.config(
                fg=RED_FG,
            )

            self.uniqa_status.config(
                text="Načtení selhalo",
                fg=RED_FG,
            )

            self.uniqa_detail.config(
                text=uniqa.error or "UNIQA není dostupná"
            )


    def _allianz_loading(self):

        self.allianz_dot.config(
            fg=ORANGE_FG,
        )

        self.allianz_status.config(
            text="Načítám Allianz...",
            fg=ORANGE_FG,
        )


    def _allianz_loaded(
        self,
        allianz,
        when,
    ):

        if allianz.available:

            self.allianz_dot.config(
                fg=GREEN_FG,
            )

            self.allianz_status.config(
                text=f"Načteno: {when}",
                fg=GREEN_FG,
            )

            self.allianz_detail.config(
                text=(
                    f"Vozidel: {len(allianz.vehicles)}"
                    f" • Období: "
                    f"{allianz.period_od} – {allianz.period_do}"
                )
            )

        else:

            self.allianz_dot.config(
                fg=RED_FG,
            )

            self.allianz_status.config(
                text="Načtení selhalo",
                fg=RED_FG,
            )

            self.allianz_detail.config(
                text=allianz.error
            )


    # ========================================================
    # FINISH
    # ========================================================

    def _finish(
        self,
        uniqa,
        allianz,
    ):

        counts = Counter(
            result.status
            for result in self.results
        )

        self.ok_uniqa = sum(
            1
            for result in self.results
            if (
                result.status == "OK"
                and self._insurance_company(result) == "UNIQA"
            )
        )

        self.ok_allianz = sum(
            1
            for result in self.results
            if (
                result.status == "OK"
                and self._insurance_company(result) == "ALLIANZ"
            )
        )

        self.ok_total = (
            self.ok_uniqa
            + self.ok_allianz
        )

        self.cards[
            "ACTIVE"
        ].config(
            text=str(
                self.active_count
            )
        )

        self.cards[
            "OK_TOTAL"
        ].config(
            text=str(
                self.ok_total
            )
        )

        self.cards[
            "OK_UNIQA"
        ].config(
            text=str(
                self.ok_uniqa
            )
        )

        self.cards[
            "OK_ALLIANZ"
        ].config(
            text=str(
                self.ok_allianz
            )
        )

        self.cards[
            "MISSING"
        ].config(
            text=str(
                counts.get(
                    "CHYBÍ V UNIQA",
                    0,
                )
            )
        )

        self.cards[
            "DEPOSIT"
        ].config(
            text=str(
                counts.get(
                    "NEPOJIŠTĚNO, ALE DEPOZIT",
                    0,
                )
            )
        )

        self.cards[
            "SOLD_UNIQA"
        ].config(
            text=str(
                counts.get(
                    "PRODANÉ, ALE V UNIQA",
                    0,
                )
            )
        )

        self.cards[
            "EXTRA_UNIQA"
        ].config(
            text=str(
                counts.get(
                    "NAVÍC V UNIQA",
                    0,
                )
            )
        )

        self.fill_table()

        if (
            uniqa.available
            and allianz.available
        ):

            self.live_dot.config(
                fg=GREEN_FG,
            )

            self.live_status.config(
                text="KONTROLA KOMPLETNÍ ✓",
                fg=GREEN_FG,
            )

        else:

            self.live_dot.config(
                fg=ORANGE_FG,
            )

            self.live_status.config(
                text="KONTROLA NEÚPLNÁ",
                fg=ORANGE_FG,
            )

        self.footer_left.config(
            text=(
                "Dokončeno: "
                + datetime.now().strftime(
                    "%d.%m.%Y %H:%M:%S"
                )
            )
        )

        self.run_button.config(
            state="normal",
            text="▶  SPUSTIT KONTROLU",
        )


    # ========================================================
    # HELPERS
    # ========================================================

    def _insurance_company(
        self,
        result,
    ) -> str:

        detail = (
            result.detail
            or ""
        ).upper()

        if "ALLIANZ" in detail:
            return "ALLIANZ"

        if "UNIQA" in detail:
            return "UNIQA"

        return ""


    def _display_status(
        self,
        result,
    ) -> str:

        if result.status == "CHYBÍ V UNIQA":
            return "CHYBÍ POJIŠTĚNÍ"

        if result.status == "NEPOJIŠTĚNO, ALE DEPOZIT":
            return "NEPOJIŠTĚNO, ALE DEPOZIT"

        if result.status == "OK":

            company = self._insurance_company(
                result
            )

            if company == "UNIQA":
                return "OK – UNIQA"

            if company == "ALLIANZ":
                return "OK – ALLIANZ"

            return "OK"

        return result.status


    # ========================================================
    # FILTERS
    # ========================================================

    def card_filter(
        self,
        key,
    ):

        self.filter_var.set(
            key
        )

        self.fill_table()


    def clear_filter(self):

        self.filter_var.set(
            "VŠE"
        )

        self.search_var.set(
            ""
        )

        self.fill_table()


    def _matches_filter(
        self,
        result,
    ) -> bool:

        selected = self.filter_var.get()

        if selected == "VŠE":
            return True

        if selected == "ACTIVE":

            return result.status in (
                "OK",
                "CHYBÍ V UNIQA",
                "NEPOJIŠTĚNO, ALE DEPOZIT",
                "SPZ NESOUHLASÍ",
                "NELZE OVĚŘIT",
            )

        if selected == "OK_TOTAL":
            return result.status == "OK"

        if selected == "OK_UNIQA":

            return (
                result.status == "OK"
                and self._insurance_company(result) == "UNIQA"
            )

        if selected == "OK_ALLIANZ":

            return (
                result.status == "OK"
                and self._insurance_company(result) == "ALLIANZ"
            )

        if selected == "MISSING":

            return (
                result.status == "CHYBÍ V UNIQA"
            )

        if selected == "DEPOSIT":

            return (
                result.status == "NEPOJIŠTĚNO, ALE DEPOZIT"
            )

        if selected == "SOLD_UNIQA":

            return (
                result.status == "PRODANÉ, ALE V UNIQA"
            )

        if selected == "EXTRA_UNIQA":

            return (
                result.status == "NAVÍC V UNIQA"
            )

        return True


    # ========================================================
    # TABLE
    # ========================================================

    def fill_table(self):

        for item in self.tree.get_children():

            self.tree.delete(
                item
            )

        search = (
            self.search_var
            .get()
            .strip()
            .upper()
        )

        shown = 0

        for result in self.results:

            if not self._matches_filter(
                result
            ):
                continue

            company = self._insurance_company(
                result
            )

            display_status = self._display_status(
                result
            )

            searchable = " ".join(
                [
                    display_status or "",
                    company or "",
                    result.vin or "",
                    result.tir_spz or "",
                    result.uniqa_spz or "",
                    result.detail or "",
                ]
            ).upper()

            if (
                search
                and search not in searchable
            ):
                continue

            self.tree.insert(
                "",
                "end",
                values=(
                    display_status,
                    company,
                    result.vin,
                    result.tir_spz or "",
                    result.uniqa_spz or "",
                    self._format_date(
                        result.datum_vykupu
                    ),
                    self._format_date(
                        result.datum_prodeje
                    ),
                    result.detail,
                ),
                tags=(
                    result.status,
                ),
            )

            shown += 1

        self.footer_right.config(
            text=f"Zobrazeno: {shown}"
        )


    def _format_date(
        self,
        value,
    ):

        if not value:
            return ""

        text = str(value).strip()

        if len(text) >= 10:

            try:

                return (
                    f"{text[8:10]}."
                    f"{text[5:7]}."
                    f"{text[0:4]}"
                )

            except Exception:
                pass

        return text


    # ========================================================
    # DETAIL
    # ========================================================

    def open_detail(
        self,
        _event=None,
    ):

        selected = self.tree.selection()

        if not selected:
            return

        values = self.tree.item(
            selected[0]
        ).get(
            "values",
            [],
        )

        if not values:
            return

        (
            status,
            company,
            vin,
            tir_spz,
            uniqa_spz,
            vykup,
            prodej,
            detail,
        ) = values

        messagebox.showinfo(
            "Detail vozidla",
            (
                f"STATUS\n"
                f"{status}\n\n"

                f"POJIŠŤOVNA\n"
                f"{company or '-'}\n\n"

                f"VIN\n"
                f"{vin}\n\n"

                f"SPZ TIRBazar\n"
                f"{tir_spz or '-'}\n\n"

                f"SPZ UNIQA\n"
                f"{uniqa_spz or '-'}\n\n"

                f"Datum výkupu\n"
                f"{vykup or '-'}\n\n"

                f"Datum prodeje\n"
                f"{prodej or '-'}\n\n"

                f"Výsledek\n"
                f"{detail}"
            ),
        )


    # ========================================================
    # ERRORS
    # ========================================================

    def _show_error(
        self,
        text,
    ):

        self.live_dot.config(
            fg=RED_FG,
        )

        self.live_status.config(
            text="CHYBA",
            fg=RED_FG,
        )

        self.run_button.config(
            state="normal",
            text="▶  SPUSTIT KONTROLU",
        )

        messagebox.showerror(
            "Kontrola pojištění",
            text,
        )


    # ========================================================
    # FILES
    # ========================================================

    def open_csv(self):

        if not self.last_csv:

            messagebox.showinfo(
                "Kontrola pojištění",
                "Nejdřív spusť kontrolu.",
            )

            return

        subprocess.run(
            [
                "open",
                str(
                    self.last_csv
                ),
            ]
        )


    def open_output_folder(self):

        folder = (
            Path(__file__)
            .resolve()
            .parent
            / "output"
        )

        folder.mkdir(
            exist_ok=True
        )

        subprocess.run(
            [
                "open",
                str(
                    folder
                ),
            ]
        )


if __name__ == "__main__":

    app = InsuranceCheckerApp()

    app.mainloop()
