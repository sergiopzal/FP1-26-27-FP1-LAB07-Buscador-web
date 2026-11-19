# buscador_gui_widgets.py
# Componentes visuales y utilidades de la interfaz gráfica (tema, gráficas, tooltips...).
# Los alumnos NO necesitan modificar este fichero.

import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

# --- Paleta de colores ---
BG = "#f3f5f9"
CARD = "#ffffff"
PRIMARY = "#2b5fc7"
PRIMARY_DARK = "#1f4aa0"
TEXT = "#1f2937"
MUTED = "#6b7280"
BORDER = "#d5dae3"
OK = "#15803d"
WARN = "#b45309"
ERROR = "#b91c1c"
NEW_BG = "#dcfce7"
HIT_BG = "#fef08a"

# Cada función del alumno: (número de ejercicio, color, descripción corta)
EJERCICIOS = {
    'normalizar_texto': (1, "#2563eb", "Limpia un texto y devuelve la lista de palabras"),
    'procesar_url_en_indice': (2, "#16a34a", "Añade al índice todas las palabras de una página"),
    'buscar_palabra_simple': (3, "#ea580c", "Consulta el índice para una palabra"),
    'buscar_palabras_or': (4, "#7c3aed", "Unión de los conjuntos de URLs de varias palabras"),
    'buscar_palabras_and': (5, "#db2777", "Intersección de los conjuntos de URLs de varias palabras"),
    'procesar_url_en_indice_top_n': (6, "#0d9488", "Añade al índice solo las N palabras más frecuentes"),
    'calcula_estadisticas_indice': (7, "#92400e", "Palabras, URLs y promedio de URLs por palabra"),
}

FUENTES = {"ui": "TkDefaultFont", "mono": "TkFixedFont"}


# --- Formato de números ---
def fmt_num(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def fmt_float(x: float, decimales: int = 2) -> str:
    texto = f"{x:,.{decimales}f}"
    return texto.replace(",", "\0").replace(".", ",").replace("\0", ".")


def fmt_tiempo(segundos: float) -> str:
    if segundos < 1e-3:
        return f"{segundos * 1e6:.0f} µs"
    if segundos < 1:
        return f"{fmt_float(segundos * 1e3, 2)} ms"
    return f"{fmt_float(segundos, 2)} s"


def format_bytes(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    elif size_bytes < 1024 ** 2:
        return f"{fmt_float(size_bytes / 1024)} KB"
    else:
        return f"{fmt_float(size_bytes / 1024 ** 2)} MB"


def mezclar_con_blanco(color: str, fraccion: float = 0.55) -> str:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (int(c + (255 - c) * fraccion) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def tamano_profundo(indice: dict) -> int:
    """Tamaño real aproximado del índice: diccionario + claves + conjuntos + URLs.
    Cada objeto se cuenta una sola vez (las URLs se comparten entre conjuntos)."""
    vistos = set()
    total = 0

    def contar(obj):
        nonlocal total
        if id(obj) not in vistos:
            vistos.add(id(obj))
            total += sys.getsizeof(obj)

    contar(indice)
    for clave, valor in indice.items():
        contar(clave)
        contar(valor)
        if isinstance(valor, (set, frozenset, list, tuple)):
            for elemento in valor:
                contar(elemento)
    return total


# --- Tema ---
def aplicar_tema(root: tk.Tk):
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    familias = set(tkfont.families(root))
    ui = "Segoe UI" if "Segoe UI" in familias else tkfont.nametofont("TkDefaultFont").actual("family")
    mono = next((f for f in ("Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New") if f in familias),
                "TkFixedFont")
    FUENTES["ui"], FUENTES["mono"] = ui, mono

    root.configure(bg=BG)
    style.configure(".", background=BG, foreground=TEXT, font=(ui, 10), bordercolor=BORDER)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD, relief="solid", borderwidth=1)
    style.configure("TLabel", background=BG)
    style.configure("Card.TLabel", background=CARD)
    style.configure("CardValue.TLabel", background=CARD, foreground=PRIMARY, font=(ui, 18, "bold"))
    style.configure("CardCaption.TLabel", background=CARD, foreground=MUTED, font=(ui, 9))
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Title.TLabel", font=(ui, 18, "bold"), foreground=PRIMARY)
    style.configure("Subtitle.TLabel", foreground=MUTED, font=(ui, 10))
    style.configure("Big.TLabel", font=(ui, 11, "bold"), foreground=PRIMARY_DARK)
    style.configure("Error.TLabel", foreground=ERROR)

    style.configure("TLabelframe", background=BG, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=BG, foreground=PRIMARY_DARK, font=(ui, 10, "bold"))

    style.configure("TButton", padding=(10, 5), background="#e5e9f2", bordercolor=BORDER)
    style.map("TButton", background=[("active", "#d5dcec"), ("disabled", "#eef0f5")],
              foreground=[("disabled", "#9aa3b2")])
    style.configure("Accent.TButton", background=PRIMARY, foreground="#ffffff", font=(ui, 10, "bold"))
    style.map("Accent.TButton", background=[("active", PRIMARY_DARK), ("disabled", "#9db5e8")],
              foreground=[("disabled", "#ffffff")])

    style.configure("TCheckbutton", background=BG)
    style.configure("TRadiobutton", background=BG)
    style.configure("TEntry", padding=4, fieldbackground="#ffffff")
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", padding=(18, 8), background="#e5e9f2", font=(ui, 10, "bold"))
    style.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", PRIMARY)])
    style.configure("Treeview", rowheight=24, background="#ffffff", fieldbackground="#ffffff")
    style.configure("Treeview.Heading", font=(ui, 10, "bold"), background="#e5e9f2")
    style.map("Treeview", background=[("selected", PRIMARY)], foreground=[("selected", "#ffffff")])
    style.configure("Horizontal.TProgressbar", troughcolor="#e5e9f2", background=PRIMARY)


def crear_texto(parent, alto: int = 5, mono: bool = False, **kw) -> tk.Text:
    """Cuadro de texto de solo lectura con las etiquetas de estilo comunes."""
    fuente = (FUENTES["mono"], 10) if mono else (FUENTES["ui"], 10)
    texto = tk.Text(parent, height=alto, wrap="word", font=fuente, bg="#ffffff", fg=TEXT, relief="solid",
                    borderwidth=1, highlightthickness=0, padx=8, pady=6, state="disabled", **kw)
    texto.tag_configure("negrita", font=(FUENTES["ui"], 10, "bold"))
    texto.tag_configure("muted", foreground=MUTED)
    texto.tag_configure("pequeno", foreground=MUTED, font=(FUENTES["ui"], 9))
    texto.tag_configure("nuevo", background=NEW_BG, foreground=OK)
    texto.tag_configure("hit", background=HIT_BG)
    texto.tag_configure("ok", foreground=OK)
    texto.tag_configure("warn", foreground=WARN)
    texto.tag_configure("error", foreground=ERROR)
    texto.tag_configure("mono", font=(FUENTES["mono"], 10))
    texto.tag_configure("enlace", foreground=PRIMARY, underline=True, font=(FUENTES["ui"], 11, "bold"))
    return texto


def poner_texto(widget: tk.Text, partes):
    """Sustituye el contenido de un Text de solo lectura.
    `partes` es una lista de cadenas o de tuplas (cadena, etiqueta, ...)."""
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    for parte in partes:
        if isinstance(parte, str):
            widget.insert("end", parte)
        else:
            widget.insert("end", parte[0], tuple(parte[1:]))
    widget.configure(state="disabled")


def texto_con_scroll(parent, alto: int = 5, mono: bool = False):
    """Devuelve (frame, text) con barra de desplazamiento vertical."""
    frame = ttk.Frame(parent)
    texto = crear_texto(frame, alto=alto, mono=mono)
    barra = ttk.Scrollbar(frame, orient="vertical", command=texto.yview)
    texto.configure(yscrollcommand=barra.set)
    texto.grid(row=0, column=0, sticky="nsew")
    barra.grid(row=0, column=1, sticky="ns")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    return frame, texto


# --- Tooltip ---
class Tooltip:
    def __init__(self, widget, texto: str, retardo: int = 450):
        self.widget, self.texto, self.retardo = widget, texto, retardo
        self._id = None
        self._ventana = None
        widget.bind("<Enter>", self._programar, add="+")
        widget.bind("<Leave>", self._ocultar, add="+")
        widget.bind("<ButtonPress>", self._ocultar, add="+")

    def _programar(self, _evento=None):
        self._ocultar()
        self._id = self.widget.after(self.retardo, self._mostrar)

    def _mostrar(self):
        if self._ventana:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._ventana = tk.Toplevel(self.widget)
        self._ventana.wm_overrideredirect(True)
        self._ventana.wm_geometry(f"+{x}+{y}")
        tk.Label(self._ventana, text=self.texto, justify="left", bg="#111827", fg="#ffffff", padx=8, pady=5,
                 font=(FUENTES["ui"], 9)).pack()

    def _ocultar(self, _evento=None):
        if self._id:
            self.widget.after_cancel(self._id)
            self._id = None
        if self._ventana:
            self._ventana.destroy()
            self._ventana = None


# --- Gráficas (Canvas, sin dependencias externas) ---
class GraficaLinea(tk.Canvas):
    """Gráfica de área/líneas: eje X = páginas procesadas, eje Y = valor (p. ej. palabras en el índice)."""

    def __init__(self, master, titulo: str = "", etiqueta_x: str = "", color: str = PRIMARY, **kw):
        kw.setdefault("height", 170)
        super().__init__(master, bg=CARD, highlightthickness=1, highlightbackground=BORDER, **kw)
        self.titulo, self.etiqueta_x, self.color = titulo, etiqueta_x, color
        self.puntos = []
        self.bind("<Configure>", lambda _e: self.dibujar())

    def set_datos(self, puntos):
        self.puntos = list(puntos)
        self.dibujar()

    def dibujar(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 80 or h < 80:
            return
        izq, der, arriba, abajo = 56, 18, 28, 28
        ancho, alto = w - izq - der, h - arriba - abajo
        self.create_text(10, 12, text=self.titulo, anchor="w", fill=PRIMARY_DARK, font=(FUENTES["ui"], 10, "bold"))
        if len(self.puntos) < 2:
            self.create_text(w / 2, h / 2, text="Aún no hay datos: indexa alguna página", fill=MUTED,
                             font=(FUENTES["ui"], 10))
            return
        xmax = max(p[0] for p in self.puntos) or 1
        ymax = max(p[1] for p in self.puntos) or 1
        for i in range(5):
            y = arriba + alto - alto * i / 4
            self.create_line(izq, y, izq + ancho, y, fill="#e5e9f2")
            self.create_text(izq - 6, y, text=fmt_num(round(ymax * i / 4)), anchor="e", fill=MUTED,
                             font=(FUENTES["ui"], 8))
        coords = [(izq + x / xmax * ancho, arriba + alto - y / ymax * alto) for x, y in self.puntos]
        area = [izq, arriba + alto] + [c for par in coords for c in par] + [coords[-1][0], arriba + alto]
        self.create_polygon(area, fill=mezclar_con_blanco(self.color, 0.8), outline="")
        self.create_line([c for par in coords for c in par], fill=self.color, width=2, smooth=False)
        xl, yl = coords[-1]
        self.create_oval(xl - 4, yl - 4, xl + 4, yl + 4, fill=self.color, outline="#ffffff")
        self.create_text(min(xl, w - der - 2), max(yl - 12, arriba), text=fmt_num(self.puntos[-1][1]), anchor="e",
                         fill=self.color, font=(FUENTES["ui"], 9, "bold"))
        self.create_text(izq, h - 12, text="0", anchor="w", fill=MUTED, font=(FUENTES["ui"], 8))
        self.create_text(izq + ancho, h - 12, text=f"{fmt_num(xmax)} {self.etiqueta_x}", anchor="e", fill=MUTED,
                         font=(FUENTES["ui"], 8))

