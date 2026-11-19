# buscador_gui.py
# Interfaz gráfica del buscador. Hace visible cómo se usan las funciones que implementa el alumno:
#   - Panel "Traza": cada llamada a una función de buscador_utiles.py queda registrada (con su ejercicio).
#   - Pestaña "Índice": estadísticas, tamaño real en memoria y contenido del índice. Desde ella se indexan páginas;
#     al hacerlo se abre una ventana con el paso a paso (texto -> normalización -> índice) y el crecimiento del índice.
#   - Pestaña "Buscar": cómo se resuelve una consulta con el índice y comparación con recorrer los textos.
#   - Pestaña "Laboratorio": pruebas con texto libre, sin necesidad de Internet.
# Los alumnos NO necesitan modificar este fichero.

import hashlib
import json
import queue
import re
import sys
import threading
import time
import traceback
import tkinter as tk
import webbrowser
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, simpledialog
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

try:
    from buscador_utiles import (
        normalizar_texto,
        procesar_url_en_indice,
        procesar_url_en_indice_top_n,
        buscar_palabra_simple,
        buscar_palabras_and,
        buscar_palabras_or,
        calcula_estadisticas_indice
    )
except ImportError as error_importacion:
    _raiz_error = tk.Tk()
    _raiz_error.withdraw()
    messagebox.showerror(
        "Error",
        "No se pudo encontrar el fichero 'buscador_utiles.py' o las funciones necesarias no están definidas.\n\n"
        f"{error_importacion}")
    sys.exit(1)

from buscador_gui_widgets import (
    BG, PRIMARY, MUTED, ERROR, EJERCICIOS, FUENTES,
    fmt_num, fmt_float, fmt_tiempo, format_bytes, mezclar_con_blanco, tamano_profundo,
    aplicar_tema, crear_texto, poner_texto, texto_con_scroll,     Tooltip, GraficaLinea
)

ARCHIVO_URLS = Path(__file__).resolve().parent / "urls_wikipedia.txt"


def cargar_urls(ruta: Path) -> list[str]:
    """Lee un fichero con una URL por línea (se ignoran las líneas vacías y las que empiezan por #)."""
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [l.strip() for l in lineas if l.strip() and not l.strip().startswith("#")]


URLS_WIKIPEDIA = cargar_urls(ARCHIVO_URLS)

HILOS_DESCARGA = 4
VENTANA_PREDESCARGA = 16        # cuántas páginas por delante de la que se está procesando se descargan
INTERVALO_REPINTADO = 0.2       # segundos entre repintados de la ventana de indexación en modo automático
LIMITE_FILAS_INDICE = 5000
TEXTO_INDICE_VACIO = ("El índice está vacío. Pulsa «Indexar Wikipedia» para construirlo "
                      "y ver, página a página, qué hacen tus funciones.")
TEXTO_SELECCIONA = "Selecciona una palabra para ver sus URLs."
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
CACHE_DIR = RAIZ_PROYECTO / "cache_paginas"                 # lo que descarga el usuario (no se sube a git)
PAQUETE_PAGINAS = RAIZ_PROYECTO / "paginas_wikipedia.zip"   # páginas de ejemplo ya descargadas (solo lectura)
TEXTO_EJEMPLO = ("¡Hola, Mundo! ¿Qué tal? El perro y el gato juegan en el jardín, pero el perro es más rápido "
                 "que el gato. En 2024 hubo 3 perros y 12 gatos (abc123). ¡Python es genial!")

# Funciones del alumno, por nombre (la GUI las invoca siempre a través de BuscadorApp.llamar)
FUNCIONES = {
    'normalizar_texto': normalizar_texto,
    'procesar_url_en_indice': procesar_url_en_indice,
    'buscar_palabra_simple': buscar_palabra_simple,
    'buscar_palabras_or': buscar_palabras_or,
    'buscar_palabras_and': buscar_palabras_and,
    'procesar_url_en_indice_top_n': procesar_url_en_indice_top_n,
    'calcula_estadisticas_indice': calcula_estadisticas_indice,
}
FUNCION_BUSQUEDA = {'simple': 'buscar_palabra_simple', 'and': 'buscar_palabras_and', 'or': 'buscar_palabras_or'}


# --- Funciones de Ayuda (Proporcionadas) ---
def obtener_texto_de_url(url: str) -> str | None:
    try:
        respuesta = requests.get(url, timeout=15, headers={'User-Agent': 'CoolBot/0.0'})
        respuesta.raise_for_status()
        soup = BeautifulSoup(respuesta.content, 'html.parser')
        for script_o_style in soup(['script', 'style', 'header', 'footer', 'nav']):
            script_o_style.decompose()
        texto = soup.get_text(separator=' ', strip=True)
        return texto
    except requests.RequestException:
        return None


_paquete = None
_cerrojo_paquete = threading.Lock()


def _nombre_cache(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest() + ".json"


def _texto_del_paquete(url: str) -> str | None:
    """Busca la página en paginas_wikipedia.zip (se lee directamente del zip, sin descomprimirlo)."""
    global _paquete
    with _cerrojo_paquete:
        try:
            if _paquete is None:
                if not PAQUETE_PAGINAS.exists():
                    return None
                _paquete = zipfile.ZipFile(PAQUETE_PAGINAS)
            return json.loads(_paquete.read(_nombre_cache(url)).decode("utf-8")).get("texto")
        except (KeyError, OSError, ValueError, zipfile.BadZipFile):
            return None


def obtener_texto_cacheado(url: str) -> tuple[str | None, bool]:
    """Devuelve (texto, venia_de_cache). Orden: carpeta cache_paginas, paquete zip y, por último, Internet
    (lo descargado se guarda en cache_paginas)."""
    ruta = CACHE_DIR / _nombre_cache(url)
    try:
        if ruta.exists():
            texto = json.loads(ruta.read_text(encoding="utf-8")).get("texto")
            if texto:
                return texto, True
    except (OSError, ValueError):
        pass
    texto = _texto_del_paquete(url)
    if texto:
        return texto, True
    texto = obtener_texto_de_url(url)
    if texto:
        try:
            CACHE_DIR.mkdir(exist_ok=True)
            ruta.write_text(json.dumps({"url": url, "texto": texto}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return texto, False


def cargar_indice() -> dict:
    return {}


def guardar_indice(indice: dict):
    pass


def titulo_de_url(url: str) -> str:
    return unquote(url.rstrip("/").rsplit("/", 1)[-1]).replace("_", " ") or url


def patron_palabras(palabras) -> re.Pattern:
    alternativas = "|".join(re.escape(p) for p in sorted(set(palabras), key=len, reverse=True))
    return re.compile(rf"(?<![^\W_])(?:{alternativas})(?![^\W_])", re.IGNORECASE)


def fragmento_con_resaltado(texto: str, patron: re.Pattern, antes: int = 90, despues: int = 110):
    """Devuelve las 'partes' (para poner_texto) de un fragmento del texto con las palabras resaltadas."""
    m = patron.search(texto)
    if not m:
        return None
    ini, fin = max(0, m.start() - antes), min(len(texto), m.end() + despues)
    trozo = " ".join(texto[ini:fin].split())
    partes = ["… " if ini > 0 else ""]
    pos = 0
    for coincidencia in patron.finditer(trozo):
        partes.append(trozo[pos:coincidencia.start()])
        partes.append((coincidencia.group(), "hit"))
        pos = coincidencia.end()
    partes.append(trozo[pos:] + (" …" if fin < len(texto) else ""))
    return partes


# --- Validación de lo que devuelven las funciones del alumno ---
def _valida_lista_str(r):
    if not isinstance(r, list):
        return f"devolvió un {type(r).__name__} en lugar de una list[str]"
    if any(not isinstance(p, str) for p in r):
        return "la lista devuelta debe contener solo cadenas (str)"


def _valida_conjunto(r):
    if not isinstance(r, (set, frozenset)):
        return f"devolvió un {type(r).__name__} en lugar de un set de URLs"


def _valida_estadisticas(r):
    if not isinstance(r, (tuple, list)) or len(r) != 3:
        return "debe devolver una tupla (num_palabras, num_urls, promedio) con 3 valores"
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in r):
        return "los tres valores de la tupla deben ser numéricos"


VALIDADORES = {
    'normalizar_texto': _valida_lista_str,
    'buscar_palabra_simple': _valida_conjunto,
    'buscar_palabras_or': _valida_conjunto,
    'buscar_palabras_and': _valida_conjunto,
    'calcula_estadisticas_indice': _valida_estadisticas,
}


class ErrorAlumno(Exception):
    """Fallo (excepción o tipo de retorno incorrecto) en una función del alumno."""

    def __init__(self, funcion: str, detalle: str):
        self.funcion, self.detalle = funcion, detalle
        super().__init__(f"{funcion} (Ej.{EJERCICIOS[funcion][0]}): {detalle}")


class TrabajoIndexacion:
    """Estado de una tanda de indexación (una URL o todas las de Wikipedia).

    Las páginas se descargan en hilos, pero se procesan siempre en el orden de la lista. En modo paso a paso
    solo se procesa una página cada vez que el usuario lo pide (permisos)."""

    def __init__(self, urls, usar_topn: bool, top_n: int, paso_a_paso: bool = False):
        self.urls = list(urls)
        self.total = len(self.urls)
        self.pendientes = queue.Queue()
        for i, url in enumerate(self.urls):
            self.pendientes.put((i, url))
        self.listos = {}                # posición -> (url, texto, venia_de_cache), ya descargadas y sin procesar
        self.usar_topn, self.top_n = usar_topn, top_n
        self.paso_a_paso = paso_a_paso
        self.permisos = 0               # páginas que el usuario ha pedido procesar en modo paso a paso
        self.hechas = self.desde_cache = 0      # hechas = páginas ya procesadas (correctas o fallidas)
        self.fallidas = []
        self.ultima = None              # última URL procesada correctamente
        self.programado = False         # hay un avance automático pendiente en el temporizador de Tk
        self.ultimo_repintado = 0.0     # instante (perf_counter) del último repintado de la ventana
        self.cancelado = threading.Event()
        self.terminado = False
        self.inicio = time.perf_counter()


# --- Lógica de la Aplicación ---
class BuscadorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Mi Buscador Web · índice invertido")
        ancho_pantalla, alto_pantalla = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        ancho, alto = min(1280, int(ancho_pantalla * 0.94)), min(940, int(alto_pantalla * 0.90))
        self.root.geometry(f"{ancho}x{alto}+{(ancho_pantalla - ancho) // 2}+{max((alto_pantalla - alto) // 2 - 20, 0)}")
        self.root.minsize(960, 640)
        aplicar_tema(root)

        self.indice = cargar_indice()
        self.textos = {}                # url -> texto de las páginas indexadas (para fragmentos y comparaciones)
        self.paginas = set()
        self.historial = [(0, 0)]       # (páginas procesadas, palabras en el índice)
        self.trabajo = None
        self.ventana_indexacion = None  # ventana modal de indexación (None si no está abierta)
        self.cola_ui = queue.Queue()
        self.contador_llamadas = Counter()
        self.chips = {}
        self._flash_ids = {}
        self.traza_visible = True
        self.num_prueba = 0
        self._orden = ("n", True)
        self._pendiente_filtro = None
        self._pendiente_lab = None
        self._detalle_urls = []
        self._ventana_comparador = None

        # Variables de control para top-N
        self.use_topn_var = tk.BooleanVar(value=False)
        self.topn_var = tk.StringVar(value="1000")

        self.crear_widgets()
        self.actualizar_modo()
        self.root.after(20, self._bombear_cola)

    # ------------------------------------------------------------------ infraestructura
    def _ui(self, funcion, *args):
        """Permite a los hilos de trabajo pedir al hilo principal que ejecute algo en la interfaz."""
        self.cola_ui.put((funcion, args))

    def _bombear_cola(self):
        limite = time.perf_counter() + 0.03
        try:
            while time.perf_counter() < limite:
                funcion, args = self.cola_ui.get_nowait()
                try:
                    funcion(*args)
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.root.after(20, self._bombear_cola)

    def llamar(self, nombre: str, *args, llamada: str = None, resumen=None, traza: bool = True):
        """Ejecuta una función del alumno anotándola en la traza y validando su resultado.
        Lanza ErrorAlumno si la función falla o devuelve algo inesperado."""
        llamada = llamada or f"{nombre}(...)"
        inicio = time.perf_counter()
        try:
            resultado = FUNCIONES[nombre](*args)
        except Exception as exc:
            detalle = f"lanzó {type(exc).__name__}: {exc}{self._ubicacion_en_alumno(exc)}"
            self._registrar_llamada(nombre)
            self.trazar(nombre, llamada, f"✖ {detalle}", time.perf_counter() - inicio, "error")
            raise ErrorAlumno(nombre, detalle) from exc
        dt = time.perf_counter() - inicio
        self._registrar_llamada(nombre)
        validador = VALIDADORES.get(nombre)
        if validador:
            problema = "devolvió None: ¿falta el return?" if resultado is None else validador(resultado)
            if problema:
                self.trazar(nombre, llamada, f"✖ {problema}", dt, "error")
                raise ErrorAlumno(nombre, problema)
        if traza:
            texto = resumen(resultado) if callable(resumen) else (resumen or "ok")
            self.trazar(nombre, llamada, texto, dt, "ok")
        return resultado

    @staticmethod
    def _ubicacion_en_alumno(exc) -> str:
        marcos = [m for m in traceback.extract_tb(exc.__traceback__) if m.filename.endswith("buscador_utiles.py")]
        return f" (buscador_utiles.py, línea {marcos[-1].lineno})" if marcos else ""

    def avisar_error(self, error: ErrorAlumno):
        messagebox.showerror(f"Revisa el Ejercicio {EJERCICIOS[error.funcion][0]}",
                             f"La función '{error.funcion}' no ha funcionado como se esperaba:\n\n{error.detalle}")

    def trazar(self, nombre: str, llamada: str, mensaje: str, dt: float = None, nivel: str = "ok"):
        num = EJERCICIOS[nombre][0]
        w = self.traza_text
        w.configure(state="normal")
        w.insert("end", datetime.now().strftime("%H:%M:%S "), "muted")
        w.insert("end", f" Ej.{num} ", f"ej{num}")
        w.insert("end", f" {llamada}", "mono")
        w.insert("end", f" → {mensaje}", nivel)
        if dt is not None:
            w.insert("end", f"  ({fmt_tiempo(dt)})", "muted")
        w.insert("end", "\n")
        self._recortar_traza()

    def trazar_gui(self, mensaje: str, nivel: str = "muted"):
        w = self.traza_text
        w.configure(state="normal")
        w.insert("end", datetime.now().strftime("%H:%M:%S "), "muted")
        w.insert("end", " GUI ", "gui")
        w.insert("end", f" {mensaje}\n", nivel)
        self._recortar_traza()

    def _recortar_traza(self):
        w = self.traza_text
        if int(w.index("end-1c").split(".")[0]) > 600:
            w.delete("1.0", "150.0")
        w.see("end")
        w.configure(state="disabled")

    def _limpiar_traza(self):
        poner_texto(self.traza_text, [])

    def _registrar_llamada(self, nombre: str):
        num, color, _ = EJERCICIOS[nombre]
        self.contador_llamadas[num] += 1
        chip = self.chips[num]
        chip.config(text=f"Ej.{num} · {fmt_num(self.contador_llamadas[num])}", bg=mezclar_con_blanco(color, 0.45))
        if num in self._flash_ids:
            self.root.after_cancel(self._flash_ids[num])
        self._flash_ids[num] = self.root.after(450, lambda: chip.config(bg=color))

    def _tags_ej(self, widget: tk.Text):
        for num, color, _ in EJERCICIOS.values():
            widget.tag_configure(f"ej{num}", background=color, foreground="#ffffff",
                                 font=(FUENTES["mono"], 9, "bold"))

    # ------------------------------------------------------------------ construcción de la interfaz
    def crear_widgets(self):
        cabecera = ttk.Frame(self.root)
        cabecera.pack(fill="x", padx=14, pady=(10, 4))
        izq = ttk.Frame(cabecera)
        izq.pack(side="left")
        ttk.Label(izq, text="Mi Buscador Web", style="Title.TLabel").pack(anchor="w")
        ttk.Label(izq, text="Índice invertido:  palabra  →  { URLs donde aparece }", style="Subtitle.TLabel").pack(anchor="w")
        der = ttk.Frame(cabecera)
        der.pack(side="right")
        ttk.Label(der, text="Llamadas a tus funciones:", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        for nombre, (num, color, descripcion) in EJERCICIOS.items():
            chip = tk.Label(der, text=f"Ej.{num} · 0", bg=color, fg="#ffffff", padx=7, pady=3,
                            font=(FUENTES["ui"], 9, "bold"))
            chip.pack(side="left", padx=2)
            Tooltip(chip, f"Ejercicio {num}: {nombre}()\n{descripcion}")
            self.chips[num] = chip
        self.btn_traza = ttk.Button(der, text="Traza ▾", command=self._alternar_traza)
        self.btn_traza.pack(side="left", padx=(12, 0))
        Tooltip(self.btn_traza, "Muestra u oculta el registro de llamadas a tus funciones")

        self.status_label = ttk.Label(self.root, text="", anchor="w", style="Muted.TLabel")
        self.status_label.pack(side="bottom", fill="x", padx=14, pady=(2, 6))

        self.paned = ttk.PanedWindow(self.root, orient="vertical")
        self.paned.pack(fill="both", expand=True, padx=10, pady=4)
        self.notebook = ttk.Notebook(self.paned)
        self.paned.add(self.notebook, weight=4)

        self.tab_indice = ttk.Frame(self.notebook)
        self.tab_buscar = ttk.Frame(self.notebook)
        self.tab_lab = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_indice, text="1 · Índice")
        self.notebook.add(self.tab_buscar, text="2 · Buscar")
        self.notebook.add(self.tab_lab, text="3 · Laboratorio")
        self.notebook.bind("<<NotebookTabChanged>>", self._al_cambiar_pestana)

        self._crear_tab_indice(self.tab_indice)
        self._crear_tab_buscar(self.tab_buscar)
        self._crear_tab_lab(self.tab_lab)
        self._crear_traza()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _crear_traza(self):
        self.traza_frame = ttk.LabelFrame(self.paned, text="Traza: llamadas a las funciones de buscador_utiles.py")
        self.paned.add(self.traza_frame, weight=1)
        barra = ttk.Frame(self.traza_frame)
        barra.pack(fill="x", padx=6, pady=(2, 0))
        ttk.Label(barra, text="Cada acción de la aplicación llama a tus funciones: aquí ves cuáles, con qué y qué devuelven.",
                  style="Muted.TLabel").pack(side="left")
        ttk.Button(barra, text="Limpiar", command=self._limpiar_traza).pack(side="right")
        marco, self.traza_text = texto_con_scroll(self.traza_frame, alto=5, mono=True)
        marco.pack(fill="both", expand=True, padx=6, pady=6)
        self._tags_ej(self.traza_text)
        self.traza_text.tag_configure("gui", background=MUTED, foreground="#ffffff", font=(FUENTES["mono"], 9, "bold"))
        self.trazar_gui("Aplicación iniciada. El índice está vacío.")
        self.root.after(250, self._ajustar_traza)

    def _ajustar_traza(self):
        """Reserva un alto fijo para la traza y deja el resto a las pestañas."""
        alto = self.paned.winfo_height()
        if self.traza_visible and alto > 350:
            self.paned.sashpos(0, alto - 170)

    def _alternar_traza(self):
        if self.traza_visible:
            self.paned.forget(self.traza_frame)
            self.btn_traza.config(text="Traza ▸")
        else:
            self.paned.add(self.traza_frame, weight=1)
            self.btn_traza.config(text="Traza ▾")
        self.traza_visible = not self.traza_visible
        self.root.after(50, self._ajustar_traza)

    # --- Barra "Construir el índice" (pestaña Índice) ---
    def _crear_barra_construir(self, tab):
        caja = ttk.LabelFrame(tab, text="Construir el índice")
        caja.grid(row=0, column=0, sticky="ew", padx=6, pady=(8, 4))
        acciones = ttk.Frame(caja)
        acciones.pack(fill="x", padx=8, pady=(8, 4))
        self.btn_wiki = ttk.Button(acciones, text=f"Indexar Wikipedia ({fmt_num(len(URLS_WIKIPEDIA))} URLs)",
                                   style="Accent.TButton", command=self.indexar_wikipedia)
        self.btn_wiki.pack(side="left")
        Tooltip(self.btn_wiki, "Indexa las páginas del fichero urls_wikipedia.txt, de una en una:\n"
                               "tú decides cuándo avanzar a la siguiente (o pasar al modo automático).")
        self.btn_url = ttk.Button(acciones, text="+ Otra URL…", command=self.indexar_url)
        self.btn_url.pack(side="left", padx=8)
        Tooltip(self.btn_url, "Indexa una página cualquiera: la descarga, la normaliza (Ej.1)\ny la añade al índice (Ej.2, o Ej.6 con top-N)")
        self.btn_mas = ttk.Menubutton(acciones, text="Más ▾")
        menu = tk.Menu(self.btn_mas, tearoff=False)
        menu.add_command(label="Vaciar descargas…", command=self.vaciar_cache)
        self.btn_mas["menu"] = menu
        self.btn_mas.pack(side="right")
        Tooltip(self.btn_mas, "«Vaciar descargas» borra las páginas que has descargado tú (carpeta cache_paginas).\n"
                              "Las páginas de ejemplo incluidas en paginas_wikipedia.zip no se tocan.")
        self.btn_vaciar = ttk.Button(acciones, text="Vaciar índice", command=self.vaciar_indice)
        self.btn_vaciar.pack(side="right", padx=6)
        Tooltip(self.btn_vaciar, "Deja el índice vacío para empezar de cero")

        opciones = ttk.Frame(caja)
        opciones.pack(fill="x", padx=8, pady=(0, 8))
        self.chk_topn = ttk.Checkbutton(opciones, text="Indexar sólo las N palabras más frecuentes",
                                        variable=self.use_topn_var, command=self.actualizar_modo)
        self.chk_topn.pack(side="left")
        ttk.Label(opciones, text="N:").pack(side="left", padx=(10, 2))
        validar = (self.root.register(lambda v: v == "" or v.isdigit()), "%P")
        self.spin_topn = ttk.Spinbox(opciones, from_=1, to=5000, textvariable=self.topn_var, width=6,
                                     validate="key", validatecommand=validar, command=self.actualizar_modo)
        self.spin_topn.pack(side="left")
        self.topn_var.trace_add("write", lambda *_: self.actualizar_modo())
        self.lbl_modo = tk.Label(opciones, text="", bg=BG, font=(FUENTES["ui"], 10, "bold"))
        self.lbl_modo.pack(side="left", padx=14)

    # --- Ventana de indexación (modal) ---
    def _abrir_ventana_indexacion(self, trabajo):
        """Abre, sobre la zona de pestañas, la ventana con el paso a paso. Deja a la vista la cabecera
        (contadores de llamadas) y la traza de la ventana principal."""
        self.root.update_idletasks()
        ancho = max(self.notebook.winfo_width(), 900)
        alto = max(self.notebook.winfo_height(), 560)
        ventana = tk.Toplevel(self.root)
        funcion = f"procesar_url_en_indice_top_n (Ej.6, N={trabajo.top_n})" if trabajo.usar_topn else "procesar_url_en_indice (Ej.2)"
        ventana.title(f"Indexando {trabajo.total} página(s) · {funcion}")
        ventana.geometry(f"{ancho}x{alto}+{self.notebook.winfo_rootx()}+{self.notebook.winfo_rooty()}")
        ventana.minsize(820, 520)
        ventana.transient(self.root)
        ventana.protocol("WM_DELETE_WINDOW", self._cerrar_ventana_indexacion)
        self.ventana_indexacion = ventana
        contenido = ttk.Frame(ventana)
        contenido.pack(fill="both", expand=True)
        self._crear_contenido_indexacion(contenido, trabajo, funcion)
        try:
            ventana.wait_visibility()
            ventana.grab_set()
        except tk.TclError:
            pass
        ventana.focus_set()

    def _cerrar_ventana_indexacion(self):
        if self.trabajo and not self.trabajo.terminado:
            self._finalizar_trabajo(self.trabajo, cancelado=True)
        ventana, self.ventana_indexacion = self.ventana_indexacion, None
        if ventana is None:
            return
        ventana.grab_release()
        ventana.destroy()
        self.actualizar_estado()
        if self.indice:
            self.refrescar_indice()

    def _crear_contenido_indexacion(self, tab, trabajo, funcion):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        color = EJERCICIOS['procesar_url_en_indice_top_n' if trabajo.usar_topn else 'procesar_url_en_indice'][1]
        tk.Label(tab, text=f"Indexando con {funcion}", bg=BG, fg=color,
                 font=(FUENTES["ui"], 11, "bold")).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))

        barra = ttk.Frame(tab)
        barra.grid(row=1, column=0, sticky="ew", padx=6, pady=2)
        barra.columnconfigure(0, weight=1)
        self.progreso = ttk.Progressbar(barra, mode="determinate")
        self.progreso.grid(row=0, column=0, sticky="ew", padx=(2, 8))
        self.botones_ventana = ttk.Frame(barra)
        self.botones_ventana.grid(row=0, column=1)
        self.btn_siguiente = ttk.Button(self.botones_ventana, text="Siguiente página ▶", style="Accent.TButton",
                                        command=self.siguiente_pagina, state="disabled")
        self.btn_siguiente.pack(side="left", padx=2)
        Tooltip(self.btn_siguiente, "Procesa la siguiente página: normalizar_texto (Ej.1) y añadirla al índice (Ej.2 / Ej.6)")
        self.btn_modo = ttk.Button(self.botones_ventana, text="Continuar en automático ⏩", command=self.alternar_modo)
        self.btn_modo.pack(side="left", padx=2)
        Tooltip(self.btn_modo, "Procesa el resto de páginas sin esperar.\nPuedes volver al modo paso a paso cuando quieras.")
        self.btn_cancelar = ttk.Button(self.botones_ventana, text="Cancelar", command=self.cancelar_trabajo)
        self.btn_cancelar.pack(side="left", padx=2)
        Tooltip(self.btn_cancelar, "Detiene la indexación (lo ya indexado se conserva)")
        self.btn_aceptar = ttk.Button(barra, text="Aceptar", style="Accent.TButton", command=self._cerrar_ventana_indexacion)
        self.lbl_progreso = ttk.Label(barra, text="", style="Muted.TLabel")
        self.lbl_progreso.grid(row=1, column=0, columnspan=2, sticky="w", padx=2)

        panel = ttk.PanedWindow(tab, orient="horizontal")
        panel.grid(row=2, column=0, sticky="nsew", padx=6, pady=(4, 6))

        izq = ttk.Frame(panel)
        izq.columnconfigure(0, weight=1)
        self.paso1 = ttk.LabelFrame(izq, text="① Texto original")
        self.paso2 = ttk.LabelFrame(izq, text="② Tras normalizar_texto (Ej.1)")
        self.paso3 = ttk.LabelFrame(izq, text="③ Efecto en el índice (Ej.2 / Ej.6)")
        self.paso_txt = []
        for fila, (marco, alto, peso) in enumerate(((self.paso1, 3, 1), (self.paso2, 4, 2), (self.paso3, 6, 3))):
            marco.grid(row=fila, column=0, sticky="nsew", pady=(0, 6))
            izq.rowconfigure(fila, weight=peso)
            contenedor, texto = texto_con_scroll(marco, alto=alto)
            contenedor.pack(fill="both", expand=True, padx=6, pady=6)
            self._tags_ej(texto)
            poner_texto(texto, [("Aquí verás, para cada página, qué hace tu código con ella.", "muted")])
            self.paso_txt.append(texto)
        panel.add(izq, weight=3)

        der = ttk.Frame(panel)
        der.columnconfigure(0, weight=1)
        der.rowconfigure(2, weight=1)
        self.lbl_crecimiento = ttk.Label(der, text=f"Índice: {fmt_num(len(self.indice))} palabras" if self.indice
                                         else "El índice está vacío.", style="Big.TLabel")
        self.lbl_crecimiento.grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.grafica_crecimiento = GraficaLinea(der, titulo="Palabras en el índice (claves del diccionario)",
                                                etiqueta_x="páginas")
        self.grafica_crecimiento.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.grafica_crecimiento.set_datos(self.historial)
        marco_log = ttk.Frame(der)
        marco_log.grid(row=2, column=0, sticky="nsew")
        columnas = ("n", "pagina", "palabras", "nuevas", "total")
        self.arbol_log = ttk.Treeview(marco_log, columns=columnas, show="headings", height=6)
        for col, texto, ancho in (("n", "#", 44), ("pagina", "Página", 130), ("palabras", "Palabras", 84),
                                  ("nuevas", "Nuevas", 76), ("total", "Índice", 76)):
            self.arbol_log.heading(col, text=texto)
            self.arbol_log.column(col, width=ancho, stretch=(col == "pagina"), anchor="w" if col == "pagina" else "e")
        barra_log = ttk.Scrollbar(marco_log, orient="vertical", command=self.arbol_log.yview)
        self.arbol_log.configure(yscrollcommand=barra_log.set)
        self.arbol_log.grid(row=0, column=0, sticky="nsew")
        barra_log.grid(row=0, column=1, sticky="ns")
        marco_log.rowconfigure(0, weight=1)
        marco_log.columnconfigure(0, weight=1)
        self.arbol_log.tag_configure("error", foreground=ERROR)
        panel.add(der, weight=2)

    # --- Pestaña Buscar ---
    def _crear_tab_buscar(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        self.search_query = tk.StringVar()
        self.search_type = tk.StringVar(value="and")

        caja = ttk.LabelFrame(tab, text="Consulta")
        caja.grid(row=0, column=0, sticky="ew", padx=6, pady=(8, 4))
        caja.columnconfigure(0, weight=1)
        self.search_entry = ttk.Entry(caja, textvariable=self.search_query, font=(FUENTES["ui"], 12))
        self.search_entry.grid(row=0, column=0, padx=8, pady=8, sticky="ew")
        self.search_entry.bind("<Return>", self.realizar_busqueda)
        self.search_button = ttk.Button(caja, text="Buscar", style="Accent.TButton", command=self.realizar_busqueda)
        self.search_button.grid(row=0, column=1, padx=(0, 8), pady=8)
        radios = ttk.Frame(caja)
        radios.grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6))
        for valor, texto in (("simple", "Simple · Ej.3 (solo la primera palabra)"),
                             ("and", "Todas (AND) · Ej.5: intersección"),
                             ("or", "Alguna (OR) · Ej.4: unión")):
            ttk.Radiobutton(radios, text=texto, variable=self.search_type, value=valor).pack(side="left", padx=(0, 18))

        marco_expl = ttk.LabelFrame(tab, text="Cómo ha buscado")
        marco_expl.grid(row=1, column=0, sticky="ew", padx=6, pady=4)
        marco_expl.columnconfigure(0, weight=1)
        self.explicacion = crear_texto(marco_expl, alto=6)
        self.explicacion.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        self._tags_ej(self.explicacion)
        poner_texto(self.explicacion, [("Escribe una o varias palabras y pulsa Buscar: verás qué consulta al índice se hace "
                                        "y cuánto tarda frente a recorrer todos los textos.", "muted")])

        marco_res = ttk.LabelFrame(tab, text="Resultados")
        marco_res.grid(row=2, column=0, sticky="nsew", padx=6, pady=(4, 6))
        contenedor, self.results_text = texto_con_scroll(marco_res, alto=6)
        contenedor.pack(fill="both", expand=True, padx=6, pady=6)

    # --- Pestaña Índice ---
    def _crear_tab_indice(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(3, weight=1)
        self._crear_barra_construir(tab)
        tarjetas = ttk.Frame(tab)
        tarjetas.grid(row=1, column=0, sticky="ew", padx=6, pady=(4, 4))
        self.tarjetas = {}
        for i, (clave, titulo) in enumerate((("palabras", "Palabras indexadas (Ej.7)"),
                                             ("urls", "URLs indexadas (Ej.7)"),
                                             ("promedio", "Promedio de URLs por palabra (Ej.7)"),
                                             ("memoria", "Tamaño real en memoria del índice"))):
            tarjeta = ttk.Frame(tarjetas, style="Card.TFrame", padding=10)
            tarjeta.grid(row=0, column=i, sticky="ew", padx=4)
            tarjetas.columnconfigure(i, weight=1)
            valor = ttk.Label(tarjeta, text="—", style="CardValue.TLabel")
            valor.pack(anchor="w")
            ttk.Label(tarjeta, text=titulo, style="CardCaption.TLabel").pack(anchor="w")
            self.tarjetas[clave] = valor

        barra = ttk.Frame(tab)
        barra.grid(row=2, column=0, sticky="ew", padx=6, pady=4)
        ttk.Label(barra, text="Filtrar palabras:").pack(side="left", padx=(2, 4))
        self.filtro_var = tk.StringVar()
        self.filtro_var.trace_add("write", lambda *_: self._programar_filtro())
        ttk.Entry(barra, textvariable=self.filtro_var, width=22).pack(side="left")
        ttk.Button(barra, text="Actualizar", command=self.refrescar_indice).pack(side="left", padx=8)
        ttk.Button(barra, text="Comparar completo vs top-N…", command=self.abrir_comparador).pack(side="left")
        self.lbl_aviso_indice = ttk.Label(barra, text="", style="Error.TLabel")
        self.lbl_aviso_indice.pack(side="left", padx=12)
        self.lbl_filas = ttk.Label(barra, text="", style="Muted.TLabel")
        self.lbl_filas.pack(side="right", padx=4)

        panel = ttk.PanedWindow(tab, orient="horizontal")
        panel.grid(row=3, column=0, sticky="nsew", padx=6, pady=(0, 6))
        izq = ttk.Frame(panel)
        izq.rowconfigure(0, weight=1)
        izq.columnconfigure(0, weight=1)
        self.arbol = ttk.Treeview(izq, columns=("palabra", "n"), show="headings", selectmode="browse")
        self.arbol.heading("palabra", text="Palabra (clave)", command=lambda: self._ordenar_por("palabra"))
        self.arbol.heading("n", text="Nº de URLs (valor)", command=lambda: self._ordenar_por("n"))
        self.arbol.column("palabra", width=220)
        self.arbol.column("n", width=120, anchor="e")
        barra_v = ttk.Scrollbar(izq, orient="vertical", command=self.arbol.yview)
        self.arbol.configure(yscrollcommand=barra_v.set)
        self.arbol.grid(row=0, column=0, sticky="nsew")
        barra_v.grid(row=0, column=1, sticky="ns")
        self.arbol.bind("<<TreeviewSelect>>", self._al_seleccionar_palabra)
        panel.add(izq, weight=2)

        der = ttk.Frame(panel)
        der.columnconfigure(0, weight=1)
        der.rowconfigure(1, weight=1)
        self.lbl_detalle = ttk.Label(der, text=TEXTO_INDICE_VACIO, style="Big.TLabel", wraplength=460, justify="left")
        self.lbl_detalle.grid(row=0, column=0, sticky="w", pady=(0, 4))
        marco_lista = ttk.Frame(der)
        marco_lista.grid(row=1, column=0, sticky="nsew")
        marco_lista.rowconfigure(0, weight=1)
        marco_lista.columnconfigure(0, weight=1)
        self.lista_urls = tk.Listbox(marco_lista, activestyle="none", relief="solid", borderwidth=1, highlightthickness=0,
                                     font=(FUENTES["ui"], 10), selectbackground=PRIMARY)
        barra_l = ttk.Scrollbar(marco_lista, orient="vertical", command=self.lista_urls.yview)
        self.lista_urls.configure(yscrollcommand=barra_l.set)
        self.lista_urls.grid(row=0, column=0, sticky="nsew")
        barra_l.grid(row=0, column=1, sticky="ns")
        self.lista_urls.bind("<Double-Button-1>", self._abrir_url_detalle)
        panel.add(der, weight=3)

    # --- Pestaña Laboratorio ---
    def _crear_tab_lab(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        marco_in = ttk.LabelFrame(tab, text="Escribe o pega un texto (no necesita Internet)")
        marco_in.grid(row=0, column=0, sticky="ew", padx=6, pady=(8, 4))
        marco_in.columnconfigure(0, weight=1)
        self.lab_entrada = tk.Text(marco_in, height=5, wrap="word", font=(FUENTES["ui"], 11), relief="solid",
                                   borderwidth=1, highlightthickness=0, padx=8, pady=6, undo=True)
        self.lab_entrada.grid(row=0, column=0, columnspan=5, sticky="ew", padx=6, pady=6)
        self.lab_entrada.bind("<KeyRelease>", lambda _e: self._programar_lab())
        self.lab_entrada.bind("<<Paste>>", lambda _e: self._programar_lab())
        self.lab_entrada.bind("<<Cut>>", lambda _e: self._programar_lab())
        ttk.Button(marco_in, text="Cargar ejemplo", command=self._lab_cargar_ejemplo).grid(row=1, column=0, padx=6, pady=(0, 6))
        ttk.Button(marco_in, text="Borrar", command=lambda: (self.lab_entrada.delete("1.0", "end"), self._actualizar_lab())
                   ).grid(row=1, column=1, padx=2, pady=(0, 6))
        self.lbl_lab = ttk.Label(marco_in, text="", style="Muted.TLabel")
        self.lbl_lab.grid(row=1, column=2, sticky="w", padx=10, pady=(0, 6))
        marco_in.columnconfigure(2, weight=1)
        self.btn_lab_indexar = ttk.Button(marco_in, text="Indexar este texto en el índice principal",
                                          style="Accent.TButton", command=self._lab_indexar)
        self.btn_lab_indexar.grid(row=1, column=4, padx=6, pady=(0, 6))

        salidas = ttk.Frame(tab)
        salidas.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.lab_paneles = []
        for i, titulo in enumerate(("Ej.1 · normalizar_texto → lista de palabras",
                                    "Recuentos de palabras (base del Ej.6)",
                                    "Mini-índice resultante (Ej.2 / Ej.6)")):
            marco = ttk.LabelFrame(salidas, text=titulo)
            marco.grid(row=0, column=i, sticky="nsew", padx=3)
            salidas.columnconfigure(i, weight=1, uniform="lab")
            contenedor, texto = texto_con_scroll(marco, alto=8, mono=(i > 0))
            contenedor.pack(fill="both", expand=True, padx=6, pady=6)
            self.lab_paneles.append(texto)
        salidas.rowconfigure(0, weight=1)
        self._actualizar_lab()

    # ------------------------------------------------------------------ modo top-N y estado
    def _leer_topn(self) -> int:
        try:
            return max(1, int(self.topn_var.get()))
        except ValueError:
            return 1000

    def actualizar_modo(self):
        if self.use_topn_var.get():
            self.spin_topn.configure(state="normal")
            self.lbl_modo.config(text=f"→ se usará procesar_url_en_indice_top_n (Ej.6) con N={self._leer_topn()}",
                                 fg=EJERCICIOS['procesar_url_en_indice_top_n'][1])
        else:
            self.spin_topn.configure(state="disabled")
            self.lbl_modo.config(text="→ se usará procesar_url_en_indice (Ej.2)",
                                 fg=EJERCICIOS['procesar_url_en_indice'][1])
        self.actualizar_estado()
        if hasattr(self, "lab_paneles"):
            self._programar_lab()

    def actualizar_estado(self):
        modo = f"top-N (N={self._leer_topn()})" if self.use_topn_var.get() else "completo"
        self.status_label.config(
            text=f"Índice: {fmt_num(len(self.indice))} palabras  ·  {fmt_num(len(self.paginas))} páginas indexadas  ·  modo de indexación: {modo}")

    def _al_cambiar_pestana(self, _evento=None):
        if self.notebook.select() == str(self.tab_indice) and self.indice:
            self.refrescar_indice()

    # ------------------------------------------------------------------ indexación
    @staticmethod
    def _normalizar_url(url: str) -> str:
        return url if "://" in url else "https://" + url

    def indexar_url(self):
        if self.trabajo and not self.trabajo.terminado:
            return
        url = simpledialog.askstring("Indexar otra URL", "Dirección de la página que quieres indexar:", parent=self.root)
        if not url or not url.strip():
            return
        self._iniciar_trabajo([self._normalizar_url(url.strip())])

    def indexar_wikipedia(self):
        if not URLS_WIKIPEDIA:
            messagebox.showwarning("Sin URLs", f"No se han encontrado URLs en el fichero:\n{ARCHIVO_URLS}")
            return
        self._iniciar_trabajo(URLS_WIKIPEDIA, paso_a_paso=True)

    def _iniciar_trabajo(self, urls, paso_a_paso: bool = False):
        if self.trabajo and not self.trabajo.terminado:
            return
        trabajo = TrabajoIndexacion(urls, self.use_topn_var.get(), self._leer_topn(), paso_a_paso)
        self.trabajo = trabajo
        self._abrir_ventana_indexacion(trabajo)
        self._estado_controles_indexacion(True)
        self._actualizar_progreso(trabajo)
        self.trazar_gui(f"Indexando {trabajo.total} página(s) con "
                        f"{'procesar_url_en_indice_top_n (N=%d)' % trabajo.top_n if trabajo.usar_topn else 'procesar_url_en_indice'}"
                        f"{' (paso a paso)' if paso_a_paso else ''}.")
        for _ in range(min(HILOS_DESCARGA, trabajo.total)):
            threading.Thread(target=self._worker_descarga, args=(trabajo,), daemon=True).start()

    def _estado_controles_indexacion(self, trabajando: bool):
        if not self.ventana_indexacion:
            return
        if trabajando:
            self._actualizar_botones_paso()
        else:
            self.botones_ventana.grid_remove()
            self.btn_aceptar.grid(row=0, column=1)
            self.btn_aceptar.focus_set()

    def _actualizar_botones_paso(self):
        trabajo = self.trabajo
        if not self.ventana_indexacion or not trabajo or trabajo.terminado:
            return
        self.btn_siguiente.config(state="normal" if trabajo.paso_a_paso else "disabled")
        self.btn_modo.config(text="Continuar en automático ⏩" if trabajo.paso_a_paso else "⏸ Volver a paso a paso")

    def _worker_descarga(self, trabajo: TrabajoIndexacion):
        """Hilo de descarga: no toca la interfaz ni el índice; entrega cada página al hilo principal."""
        while not trabajo.cancelado.is_set():
            try:
                posicion, url = trabajo.pendientes.get_nowait()
            except queue.Empty:
                return
            while posicion >= trabajo.hechas + VENTANA_PREDESCARGA and not trabajo.cancelado.wait(0.05):
                pass    # no se descarga mucho más allá de la página que se está procesando
            if trabajo.cancelado.is_set():
                return
            try:
                texto, de_cache = obtener_texto_cacheado(url)
            except Exception:
                texto, de_cache = None, False
            self._ui(self._recibir_pagina, trabajo, posicion, url, texto, de_cache)

    def _recibir_pagina(self, trabajo: TrabajoIndexacion, posicion: int, url: str, texto, de_cache: bool):
        if trabajo.terminado:
            return
        trabajo.listos[posicion] = (url, texto, de_cache)
        self._avanzar(trabajo)

    def siguiente_pagina(self):
        trabajo = self.trabajo
        if not trabajo or trabajo.terminado or not trabajo.paso_a_paso:
            return
        trabajo.permisos = 1
        self._avanzar(trabajo)

    def alternar_modo(self):
        trabajo = self.trabajo
        if not trabajo or trabajo.terminado:
            return
        trabajo.paso_a_paso = not trabajo.paso_a_paso
        trabajo.permisos = 0
        self.trazar_gui("Modo paso a paso." if trabajo.paso_a_paso else "Modo automático: se procesan las páginas seguidas.")
        self._actualizar_botones_paso()
        self._actualizar_progreso(trabajo)
        self._avanzar(trabajo)

    def _avanzar(self, trabajo: TrabajoIndexacion, desde_temporizador: bool = False):
        """Procesa, en orden, las páginas ya descargadas. En paso a paso procesa solo la que el usuario ha pedido;
        en automático procesa una por llamada y repinta la ventana como mucho cada INTERVALO_REPINTADO segundos.
        Las fallidas se anotan sin gastar un «paso»."""
        if desde_temporizador:
            trabajo.programado = False
        if trabajo.terminado or trabajo.programado:
            return
        repintar = True
        while trabajo.hechas in trabajo.listos:
            url, texto, de_cache = trabajo.listos[trabajo.hechas]
            if texto and trabajo.paso_a_paso and trabajo.permisos <= 0:
                break
            del trabajo.listos[trabajo.hechas]
            trabajo.hechas += 1
            if not texto:
                trabajo.fallidas.append(url)
                self.trazar_gui(f"No se pudo obtener el contenido de {url}", "warn")
                self.arbol_log.insert("", "end", values=(trabajo.hechas, titulo_de_url(url), "—", "error", fmt_num(len(self.indice))),
                                      tags=("error",))
                self.arbol_log.see(self.arbol_log.get_children()[-1])
                continue
            trabajo.desde_cache += de_cache
            trabajo.ultima = url
            repintar = (trabajo.paso_a_paso or trabajo.hechas >= trabajo.total or trabajo.hechas not in trabajo.listos
                        or time.perf_counter() - trabajo.ultimo_repintado >= INTERVALO_REPINTADO)
            try:
                self.procesar_pagina(url, texto, trabajo.usar_topn, trabajo.top_n, mostrar=repintar)
            except ErrorAlumno as error:
                self._finalizar_trabajo(trabajo, error=error)
                return
            if trabajo.paso_a_paso:
                trabajo.permisos -= 1
            break
        if repintar:
            trabajo.ultimo_repintado = time.perf_counter()
            self._actualizar_progreso(trabajo)
            self.root.update_idletasks()    # repinta ahora; si no, en modo automático la ventana no se actualizaría hasta el final
        if trabajo.hechas >= trabajo.total:
            self._finalizar_trabajo(trabajo)
        elif not trabajo.paso_a_paso and trabajo.hechas in trabajo.listos:
            trabajo.programado = True
            self.root.after(1, self._avanzar, trabajo, True)

    def _actualizar_progreso(self, trabajo: TrabajoIndexacion):
        self.progreso.configure(value=trabajo.hechas / trabajo.total * 100)
        resumen = f"{trabajo.hechas}/{trabajo.total} páginas · {trabajo.desde_cache} desde caché · {len(trabajo.fallidas)} fallidas"
        if trabajo.ultima:
            resumen += f" · última: {titulo_de_url(trabajo.ultima)}"
        if trabajo.paso_a_paso and trabajo.hechas < trabajo.total:
            siguiente = titulo_de_url(trabajo.urls[trabajo.hechas])
            resumen += f"   ▶ Siguiente: «{siguiente}» (pulsa «Siguiente página»)"
        elif trabajo.hechas == 0:
            resumen = f"Descargando 0/{trabajo.total}..."
        self.lbl_progreso.config(text=resumen)

    def cancelar_trabajo(self):
        if self.trabajo and not self.trabajo.terminado:
            self._finalizar_trabajo(self.trabajo, cancelado=True)

    def _finalizar_trabajo(self, trabajo: TrabajoIndexacion, error: ErrorAlumno = None, cancelado: bool = False):
        trabajo.terminado = True
        trabajo.cancelado.set()
        self._estado_controles_indexacion(False)
        self.actualizar_estado()
        duracion = time.perf_counter() - trabajo.inicio
        correctas = trabajo.hechas - len(trabajo.fallidas)
        resumen = (f"{correctas} páginas indexadas, {len(trabajo.fallidas)} fallidas, "
                   f"{trabajo.desde_cache} desde caché · {fmt_tiempo(duracion)}")
        if error:
            self.lbl_progreso.config(text="Indexación detenida por un error en tu código.", style="Error.TLabel")
            self.trazar_gui("Indexación detenida: " + str(error), "error")
            self.avisar_error(error)
        elif cancelado:
            self.lbl_progreso.config(text="Cancelado. " + resumen)
            self.trazar_gui("Indexación cancelada. " + resumen, "warn")
        else:
            fallo_unico = trabajo.total == 1 and trabajo.fallidas
            self.lbl_progreso.config(
                text=f"No se pudo obtener el contenido de {trabajo.fallidas[0]}" if fallo_unico else "Completado. " + resumen,
                style="Error.TLabel" if fallo_unico else "Muted.TLabel")
            self.trazar_gui("Indexación completada. " + resumen, "ok")

    def procesar_pagina(self, url: str, texto: str, usar_topn: bool, top_n: int, mostrar: bool = True):
        """Indexa una página llamando a las funciones del alumno. Con mostrar=True actualiza además el paso a paso
        (con mostrar=False solo se anota la fila de la tabla)."""
        antes_pal, antes_pag = len(self.indice), len(self.paginas)
        palabras = self.llamar(
            'normalizar_texto', texto, llamada=f"normalizar_texto(texto de {fmt_num(len(texto))} caracteres)",
            resumen=lambda r: f"{fmt_num(len(r))} palabras ({fmt_num(len(set(r)))} distintas)")
        contador = Counter(palabras)
        if usar_topn:
            elegidas = [p for p, _ in contador.most_common(top_n)]
            nombre = 'procesar_url_en_indice_top_n'
            argumentos = (url, texto, self.indice, top_n)
            llamada = f"procesar_url_en_indice_top_n(url, texto, indice, {top_n})"
        else:
            elegidas = list(contador)
            nombre = 'procesar_url_en_indice'
            argumentos = (url, texto, self.indice)
            llamada = "procesar_url_en_indice(url, texto, indice)"
        nuevas = [p for p in elegidas if p not in self.indice] if mostrar else []
        self.llamar(nombre, *argumentos, llamada=llamada,
                    resumen=lambda _: f"+{fmt_num(len(self.indice) - antes_pal)} palabras nuevas · "
                                      f"índice: {fmt_num(antes_pal)} → {fmt_num(len(self.indice))} palabras")
        aviso = ""
        if elegidas and url not in self.indice.get(elegidas[0], ()):
            aviso = (f"⚠ Tras llamar a {nombre}, la URL no aparece en el índice para la palabra '{elegidas[0]}'. "
                     "¿Está implementada la función?")
            self.trazar(nombre, llamada, aviso, None, "warn")

        self.textos[url] = texto
        self.paginas.add(url)
        self.historial.append((len(self.historial), len(self.indice)))
        self.actualizar_estado()
        if not self.ventana_indexacion:     # p. ej. texto indexado desde el Laboratorio
            return
        self.arbol_log.insert("", "end", values=(len(self.historial) - 1, titulo_de_url(url), fmt_num(len(palabras)),
                                                 f"+{fmt_num(len(self.indice) - antes_pal)}", fmt_num(len(self.indice))))
        if not mostrar:
            return
        self._mostrar_paso_a_paso(url, texto, palabras, contador, elegidas, nuevas, usar_topn, top_n, antes_pal, aviso)
        self.arbol_log.see(self.arbol_log.get_children()[-1])
        self.grafica_crecimiento.set_datos(self.historial)
        self.lbl_crecimiento.config(
            text=f"Índice: {fmt_num(antes_pal)} → {fmt_num(len(self.indice))} palabras "
                 f"(+{fmt_num(len(self.indice) - antes_pal)})\nPáginas indexadas: {antes_pag} → {len(self.paginas)}")

    def _mostrar_paso_a_paso(self, url, texto, palabras, contador, elegidas, nuevas, usar_topn, top_n, antes_pal, aviso):
        brutas = len(texto.split())
        self.paso1.config(text=f"① Texto original · {titulo_de_url(url)} · {fmt_num(len(texto))} caracteres")
        poner_texto(self.paso_txt[0], [" ".join(texto[:600].split()) + (" …" if len(texto) > 600 else "")])

        conjunto = set(palabras)
        descartadas, vistas = [], set()
        for token in re.findall(r"[^\W_]+", texto[:5000].lower()):
            if token not in conjunto and token not in vistas:
                vistas.add(token)
                descartadas.append(token)
            if len(descartadas) >= 14:
                break
        self.paso2.config(text=f"② Tras normalizar_texto (Ej.1) · {fmt_num(brutas)} palabras brutas → "
                               f"{fmt_num(len(palabras))} útiles ({fmt_num(len(conjunto))} distintas)")
        poner_texto(self.paso_txt[1], [
            " · ".join(palabras[:70]) + (" …" if len(palabras) > 70 else ""),
            "\n\nDescartadas (ejemplos): ", (" · ".join(descartadas) or "ninguna", "muted"),
        ])

        conjunto_nuevas = set(nuevas)
        existentes = [p for p in elegidas if p not in conjunto_nuevas]
        partes = []
        if aviso:
            partes.append((aviso + "\n\n", "warn"))
        if usar_topn:
            partes += [(f"Top-N (N={top_n}): ", "negrita"),
                       f"de {fmt_num(len(contador))} palabras distintas solo se indexan las {fmt_num(len(elegidas))} más frecuentes.\n",
                       ("Las más frecuentes: ", "muted"),
                       " · ".join(f"{p} ({c})" for p, c in contador.most_common(12)) + "\n\n"]
        else:
            partes.append(f"Se indexan las {fmt_num(len(elegidas))} palabras distintas del texto.\n\n")
        partes += [(f"+{fmt_num(len(self.indice) - antes_pal)} palabras nuevas ", "negrita"),
                   "(nuevas claves del diccionario): "]
        for p in nuevas[:60]:
            partes += [(p, "nuevo"), " "]
        if len(nuevas) > 60:
            partes.append((f"… y {fmt_num(len(nuevas) - 60)} más", "muted"))
        partes += [(f"\n\n{fmt_num(len(existentes))} palabras ya existían ", "negrita"),
                   "(su conjunto de URLs gana una URL más): " + " · ".join(existentes[:15]) + (" …" if len(existentes) > 15 else "")]
        poner_texto(self.paso_txt[2], partes)

    def vaciar_indice(self):
        if self.indice and not messagebox.askyesno("Vaciar índice", "¿Seguro que quieres vaciar el índice?"):
            return
        self.indice.clear()
        self.textos.clear()
        self.paginas.clear()
        self.historial = [(0, 0)]
        self.actualizar_estado()
        self.refrescar_indice()
        self.trazar_gui("Índice vaciado.")

    def vaciar_cache(self):
        ficheros = list(CACHE_DIR.glob("*.json")) if CACHE_DIR.exists() else []
        if not ficheros:
            messagebox.showinfo("Descargas", "No hay páginas descargadas en la carpeta cache_paginas.")
            return
        if messagebox.askyesno("Vaciar descargas", f"Se borrarán {len(ficheros)} páginas descargadas (carpeta cache_paginas).\n"
                                                    "Las del paquete paginas_wikipedia.zip no se tocan. ¿Continuar?"):
            for fichero in ficheros:
                try:
                    fichero.unlink()
                except OSError:
                    pass
            self.trazar_gui(f"Descargas borradas ({len(ficheros)} páginas).")

    # ------------------------------------------------------------------ búsqueda
    def realizar_busqueda(self, _evento=None):
        consulta = self.search_query.get().strip()
        tipo = self.search_type.get()
        if not consulta:
            return
        if not self.indice:
            poner_texto(self.explicacion, [("El índice está vacío: indexa algunas páginas antes de buscar.", "warn")])
            poner_texto(self.results_text, [])
            return
        try:
            palabras = self.llamar('normalizar_texto', consulta, llamada=f"normalizar_texto({consulta!r})", resumen=repr)
            if not palabras:
                poner_texto(self.explicacion, [("La consulta solo contiene palabras huecas (de, la, que...) o símbolos, "
                                                "que no se indexan: no hay nada que buscar.", "warn")])
                poner_texto(self.results_text, [("No se encontraron resultados.", "muted")])
                return
            usadas = list(dict.fromkeys(palabras))
            if tipo == "simple":
                usadas = usadas[:1]
            nombre = FUNCION_BUSQUEDA[tipo]
            resultado = self.llamar(nombre, consulta, self.indice, llamada=f"{nombre}({consulta!r}, indice)",
                                    resumen=lambda r: f"{fmt_num(len(r))} URLs")
            if tipo == "simple":
                por_palabra = {usadas[0]: resultado}
            else:
                por_palabra = {p: self.llamar('buscar_palabra_simple', p, self.indice, llamada=f"buscar_palabra_simple({p!r}, indice)",
                                              resumen=lambda r: f"{fmt_num(len(r))} URLs") for p in usadas}
        except ErrorAlumno as error:
            poner_texto(self.explicacion, [(f"✖ {error}", "error")])
            poner_texto(self.results_text, [])
            self.avisar_error(error)
            return

        esperado = None
        if tipo == "and":
            esperado = set.intersection(*(set(s) for s in por_palabra.values()))
        elif tipo == "or":
            esperado = set().union(*por_palabra.values())
        tiempo_indice = self._medir(FUNCIONES[nombre], consulta, self.indice)
        lineal, tiempo_lineal = self._busqueda_lineal(usadas, tipo)
        self._explicar_busqueda(consulta, palabras, usadas, tipo, por_palabra, resultado, esperado, tiempo_indice, tiempo_lineal, lineal)
        self.mostrar_resultados(resultado, usadas, por_palabra)

    @staticmethod
    def _medir(funcion, *args, repeticiones: int = 30) -> float:
        inicio = time.perf_counter()
        for _ in range(repeticiones):
            funcion(*args)
        return (time.perf_counter() - inicio) / repeticiones

    def _busqueda_lineal(self, palabras, tipo):
        """Búsqueda 'ingenua' sin índice: recorre el texto de todas las páginas en cada consulta."""
        patrones = [re.compile(rf"(?<![^\W_]){re.escape(p)}(?![^\W_])") for p in palabras]
        combinar = any if tipo == "or" else all
        inicio = time.perf_counter()
        encontradas = set()
        for url, texto in self.textos.items():
            bajo = texto.lower()
            if combinar(patron.search(bajo) is not None for patron in patrones):
                encontradas.add(url)
        return encontradas, time.perf_counter() - inicio

    def _explicar_busqueda(self, consulta, palabras, usadas, tipo, por_palabra, resultado, esperado,
                           t_indice, t_lineal, lineal):
        def ej(num):
            return (f" Ej.{num} ", f"ej{num}")

        partes = [ej(1), f"  Normalizar la consulta:  {consulta!r}  →  {palabras}\n"]
        if tipo == "simple" and len(set(palabras)) > 1:
            partes += [("      Búsqueda simple: solo se usa la primera palabra.\n", "muted")]
        partes += [ej(3), "  Consultar el índice:  " + "   ".join(f"{p} → {fmt_num(len(s))} URLs" for p, s in por_palabra.items()) + "\n"]
        if tipo == "and":
            partes += [ej(5), "  Intersección (AND):  " + " ∩ ".join(fmt_num(len(s)) for s in por_palabra.values())
                       + f" = {fmt_num(len(resultado))} URLs\n"]
        elif tipo == "or":
            partes += [ej(4), "  Unión (OR):  " + " ∪ ".join(fmt_num(len(s)) for s in por_palabra.values())
                       + f" = {fmt_num(len(resultado))} URLs\n"]
        if esperado is not None and set(resultado) != esperado:
            partes += [(f"⚠ El resultado devuelto ({fmt_num(len(resultado))} URLs) no coincide con la "
                        f"{'intersección' if tipo == 'and' else 'unión'} de los conjuntos por palabra "
                        f"({fmt_num(len(esperado))} URLs). Revisa el ejercicio.\n", "warn")]
        veloz = f"×{fmt_num(round(t_lineal / t_indice))} más rápido" if t_indice > 0 else ""
        partes += [("⏱ ", "negrita"), f"Con el índice: {fmt_tiempo(t_indice)}   ·   Recorriendo el texto de las "
                   f"{fmt_num(len(self.textos))} páginas: {fmt_tiempo(t_lineal)}   ", (veloz, "negrita", "ok")]
        if len(lineal) != len(resultado):
            partes += [(f"\nEl recorrido encuentra {fmt_num(len(lineal))} páginas y el índice {fmt_num(len(resultado))}: "
                        "el índice solo sabe lo que dejó normalizar_texto (p. ej. «imperio no se limpia, porque « no está "
                        "en PUNTUACION) y el modo top-N.", "muted")]
        poner_texto(self.explicacion, partes)
        self.trazar_gui(f"Búsqueda {tipo.upper()} {palabras}: {fmt_num(len(resultado))} URLs · índice {fmt_tiempo(t_indice)} "
                        f"frente a recorrido lineal {fmt_tiempo(t_lineal)}")

    def mostrar_resultados(self, urls, palabras, por_palabra):
        w = self.results_text
        w.configure(state="normal")
        w.delete("1.0", "end")
        for tag in w.tag_names():
            if tag.startswith("url"):
                w.tag_delete(tag)
        if not urls:
            w.insert("end", "No se encontraron resultados.", "muted")
            w.configure(state="disabled")
            return
        total = len(palabras)
        puntuados = sorted(((sum(1 for p in palabras if url in por_palabra[p]), url) for url in urls),
                           key=lambda par: (-par[0], titulo_de_url(par[1]).lower()))
        w.insert("end", f"Se encontraron {fmt_num(len(urls))} resultados", "negrita")
        if len(puntuados) > 100:
            w.insert("end", " (se muestran los 100 primeros)", "muted")
        w.insert("end", ":\n\n")
        patron = patron_palabras(palabras)
        for i, (aciertos, url) in enumerate(puntuados[:100]):
            etiqueta = f"url{i}"
            w.insert("end", titulo_de_url(url), ("enlace", etiqueta))
            w.insert("end", f"   coincide con {aciertos} de {total} palabras\n", "pequeno")
            w.insert("end", url + "\n", "pequeno")
            fragmento = fragmento_con_resaltado(self.textos.get(url, ""), patron)
            if fragmento:
                for parte in fragmento:
                    if isinstance(parte, str):
                        w.insert("end", parte)
                    else:
                        w.insert("end", parte[0], parte[1:])
                w.insert("end", "\n")
            w.insert("end", "\n")
            w.tag_bind(etiqueta, "<Button-1>", lambda _e, u=url: self.abrir_enlace(u))
            w.tag_bind(etiqueta, "<Enter>", lambda _e: w.config(cursor="hand2"))
            w.tag_bind(etiqueta, "<Leave>", lambda _e: w.config(cursor=""))
        w.configure(state="disabled")

    def abrir_enlace(self, url):
        if url.startswith(("http://", "https://")):
            webbrowser.open_new(url)

    # ------------------------------------------------------------------ pestaña Índice
    def refrescar_indice(self):
        self._actualizar_tarjetas()
        self._poblar_arbol()
        if not self.indice:
            self.lbl_detalle.config(text=TEXTO_INDICE_VACIO)
            self.lista_urls.delete(0, "end")
        elif self.lbl_detalle.cget("text") == TEXTO_INDICE_VACIO:
            self.lbl_detalle.config(text=TEXTO_SELECCIONA)

    def _actualizar_tarjetas(self):
        self.lbl_aviso_indice.config(text="")
        try:
            palabras, urls, promedio = self.llamar(
                'calcula_estadisticas_indice', self.indice, llamada="calcula_estadisticas_indice(indice)",
                resumen=lambda r: f"{fmt_num(r[0])} palabras, {fmt_num(r[1])} URLs, promedio {fmt_float(r[2])}")
            self.tarjetas["palabras"].config(text=fmt_num(palabras))
            self.tarjetas["urls"].config(text=fmt_num(urls))
            self.tarjetas["promedio"].config(text=fmt_float(promedio))
        except ErrorAlumno as error:
            for clave in ("palabras", "urls", "promedio"):
                self.tarjetas[clave].config(text="—")
            self.lbl_aviso_indice.config(text=f"✖ {error}")
        self.tarjetas["memoria"].config(text=format_bytes(tamano_profundo(self.indice)))

    def _programar_filtro(self):
        if self._pendiente_filtro:
            self.root.after_cancel(self._pendiente_filtro)
        self._pendiente_filtro = self.root.after(250, self._poblar_arbol)

    def _ordenar_por(self, columna: str):
        actual, descendente = self._orden
        self._orden = (columna, not descendente if columna == actual else columna == "n")
        self._poblar_arbol()

    def _poblar_arbol(self):
        self._pendiente_filtro = None
        filtro = self.filtro_var.get().strip().lower()
        elementos = [(str(p), len(u)) for p, u in self.indice.items() if filtro in str(p).lower()]
        columna, descendente = self._orden
        if columna == "n":
            elementos.sort(key=lambda e: (e[1], e[0]), reverse=descendente)
        else:
            elementos.sort(key=lambda e: e[0], reverse=descendente)
        self.arbol.delete(*self.arbol.get_children())
        for palabra, n in elementos[:LIMITE_FILAS_INDICE]:
            try:
                self.arbol.insert("", "end", iid=palabra, values=(palabra, fmt_num(n)))
            except tk.TclError:
                pass
        flecha = " ▼" if descendente else " ▲"
        self.arbol.heading("palabra", text="Palabra (clave)" + (flecha if columna == "palabra" else ""))
        self.arbol.heading("n", text="Nº de URLs (valor)" + (flecha if columna == "n" else ""))
        mostradas = min(len(elementos), LIMITE_FILAS_INDICE)
        self.lbl_filas.config(text=f"{fmt_num(mostradas)} de {fmt_num(len(self.indice))} palabras"
                                   + (" (filtra para ver más)" if len(elementos) > mostradas else ""))

    def _al_seleccionar_palabra(self, _evento=None):
        seleccion = self.arbol.selection()
        if not seleccion:
            return
        palabra = seleccion[0]
        urls = sorted(self.indice.get(palabra, ()), key=lambda u: titulo_de_url(u).lower())
        self._detalle_urls = urls
        self.lbl_detalle.config(text=f"'{palabra}'  →  {fmt_num(len(urls))} URLs  (doble clic para abrir)")
        self.lista_urls.delete(0, "end")
        for url in urls:
            self.lista_urls.insert("end", f"{titulo_de_url(url)}   —   {url}")

    def _abrir_url_detalle(self, _evento=None):
        seleccion = self.lista_urls.curselection()
        if seleccion:
            self.abrir_enlace(self._detalle_urls[seleccion[0]])

    # ------------------------------------------------------------------ comparador completo vs top-N
    def abrir_comparador(self):
        if not self.textos:
            messagebox.showinfo("Comparar", "Indexa antes algunas páginas: el comparador reutiliza sus textos.")
            return
        if self._ventana_comparador is not None and self._ventana_comparador.winfo_exists():
            self._ventana_comparador.lift()
            return
        ventana = tk.Toplevel(self.root)
        self._ventana_comparador = ventana
        ventana.title("Índice completo frente a índice top-N")
        ventana.geometry("860x640")
        ventana.configure(bg=BG)
        ventana.transient(self.root)
        estado = {"indices": None}

        cuerpo = ttk.Frame(ventana, padding=12)
        cuerpo.pack(fill="both", expand=True)
        cuerpo.columnconfigure(0, weight=1)
        ttk.Label(cuerpo, text=f"Se construyen dos índices temporales con las {len(self.textos)} páginas ya descargadas "
                               "(el índice principal no se modifica).", style="Subtitle.TLabel").grid(row=0, column=0, sticky="w")
        fila = ttk.Frame(cuerpo)
        fila.grid(row=1, column=0, sticky="ew", pady=8)
        ttk.Label(fila, text="N (palabras más frecuentes por página):").pack(side="left")
        n_var = tk.StringVar(value=str(self._leer_topn()))
        ttk.Spinbox(fila, from_=1, to=5000, textvariable=n_var, width=7).pack(side="left", padx=6)
        boton_calc = ttk.Button(fila, text="Calcular", style="Accent.TButton")
        boton_calc.pack(side="left")
        lbl_estado = ttk.Label(fila, text="", style="Muted.TLabel")
        lbl_estado.pack(side="left", padx=10)

        tabla = ttk.Treeview(cuerpo, columns=("metrica", "completo", "topn", "dif"), show="headings", height=4)
        for col, texto, ancho in (("metrica", "Métrica", 260), ("completo", "Completo (Ej.2)", 170),
                                  ("topn", "Top-N (Ej.6)", 170), ("dif", "Diferencia", 110)):
            tabla.heading(col, text=texto)
            tabla.column(col, width=ancho, anchor="w" if col == "metrica" else "e")
        tabla.grid(row=2, column=0, sticky="ew")

        prueba = ttk.LabelFrame(cuerpo, text="¿Qué resultados se pierden al indexar solo las N palabras más frecuentes?")
        prueba.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        cuerpo.rowconfigure(3, weight=1)
        prueba.columnconfigure(0, weight=1)
        prueba.rowconfigure(2, weight=1)
        consulta_var = tk.StringVar(value=self.search_query.get() or "imperio roma")
        tipo_var = tk.StringVar(value=self.search_type.get())
        entrada = ttk.Entry(prueba, textvariable=consulta_var)
        entrada.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        boton_probar = ttk.Button(prueba, text="Probar consulta", state="disabled")
        boton_probar.grid(row=0, column=1, padx=8)
        radios = ttk.Frame(prueba)
        radios.grid(row=1, column=0, columnspan=2, sticky="w", padx=8)
        for valor, texto in (("simple", "Simple"), ("and", "Todas (AND)"), ("or", "Alguna (OR)")):
            ttk.Radiobutton(radios, text=texto, variable=tipo_var, value=valor).pack(side="left", padx=(0, 14))
        contenedor, salida = texto_con_scroll(prueba, alto=8)
        contenedor.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=8)

        def calcular():
            try:
                n = max(1, int(n_var.get()))
            except ValueError:
                return
            boton_calc.config(state="disabled")
            boton_probar.config(state="disabled")
            lbl_estado.config(text="Calculando...")
            self._calcular_comparacion(ventana, dict(self.textos), n, tabla, estado, lbl_estado, boton_calc, boton_probar)

        def probar():
            if estado["indices"]:
                self._probar_consulta_comparador(consulta_var.get(), tipo_var.get(), estado["indices"], salida)

        boton_calc.config(command=calcular)
        boton_probar.config(command=probar)
        entrada.bind("<Return>", lambda _e: probar())
        calcular()

    def _calcular_comparacion(self, ventana, textos, n, tabla, estado, lbl_estado, boton_calc, boton_probar):
        def trabajo():
            try:
                completo, reducido = {}, {}
                inicio = time.perf_counter()
                for url, texto in textos.items():
                    FUNCIONES['procesar_url_en_indice'](url, texto, completo)
                t_completo = time.perf_counter() - inicio
                inicio = time.perf_counter()
                for url, texto in textos.items():
                    FUNCIONES['procesar_url_en_indice_top_n'](url, texto, reducido, n)
                t_reducido = time.perf_counter() - inicio
                self._ui(self._mostrar_comparacion, ventana, tabla, estado, lbl_estado, boton_calc, boton_probar,
                         completo, reducido, n, t_completo, t_reducido)
            except Exception as exc:
                self._ui(self._error_comparacion, ventana, lbl_estado, boton_calc, exc)

        threading.Thread(target=trabajo, daemon=True).start()

    def _error_comparacion(self, ventana, lbl_estado, boton_calc, exc):
        if ventana.winfo_exists():
            lbl_estado.config(text=f"✖ Error en tu código: {type(exc).__name__}: {exc}", style="Error.TLabel")
            boton_calc.config(state="normal")

    def _mostrar_comparacion(self, ventana, tabla, estado, lbl_estado, boton_calc, boton_probar,
                             completo, reducido, n, t_completo, t_reducido):
        if not ventana.winfo_exists():
            return
        estado["indices"] = (completo, reducido)

        def relaciones(indice):
            return sum(len(u) for u in indice.values())

        def dif(a, b):
            return f"{fmt_float((b - a) / a * 100, 1)} %" if a else "—"

        tam_c, tam_r = tamano_profundo(completo), tamano_profundo(reducido)
        filas = (("Palabras en el índice (claves)", fmt_num(len(completo)), fmt_num(len(reducido)), dif(len(completo), len(reducido))),
                 ("Relaciones palabra → URL", fmt_num(relaciones(completo)), fmt_num(relaciones(reducido)),
                  dif(relaciones(completo), relaciones(reducido))),
                 ("Tamaño real en memoria", format_bytes(tam_c), format_bytes(tam_r), dif(tam_c, tam_r)),
                 ("Tiempo de construcción", fmt_tiempo(t_completo), fmt_tiempo(t_reducido), dif(t_completo, t_reducido)))
        tabla.delete(*tabla.get_children())
        for fila in filas:
            tabla.insert("", "end", values=fila)
        lbl_estado.config(text=f"Calculado con N={n}.", style="Muted.TLabel")
        boton_calc.config(state="normal")
        boton_probar.config(state="normal")
        self.trazar_gui(f"Comparación completo vs top-N={n}: memoria {format_bytes(tam_c)} → {format_bytes(tam_r)}")

    def _probar_consulta_comparador(self, consulta, tipo, indices, salida):
        completo, reducido = indices
        funcion = FUNCIONES[FUNCION_BUSQUEDA[tipo]]
        try:
            a, b = set(funcion(consulta, completo)), set(funcion(consulta, reducido))
        except Exception as exc:
            poner_texto(salida, [(f"✖ Error en tu código: {type(exc).__name__}: {exc}", "error")])
            return
        perdidas = sorted(a - b, key=lambda u: titulo_de_url(u).lower())
        partes = [(f"Índice completo: {fmt_num(len(a))} resultados   ·   Top-N: {fmt_num(len(b))} resultados\n", "negrita")]
        if perdidas:
            partes += [(f"\nSe pierden {fmt_num(len(perdidas))} páginas porque la palabra buscada no está entre las más frecuentes de la página:\n", "warn")]
            partes += [f"  · {titulo_de_url(u)}\n" for u in perdidas[:25]]
        else:
            partes += [("\nNo se pierde ningún resultado con esta consulta.", "ok")]
        poner_texto(salida, partes)

    # ------------------------------------------------------------------ pestaña Laboratorio
    def _lab_cargar_ejemplo(self):
        self.lab_entrada.delete("1.0", "end")
        self.lab_entrada.insert("1.0", TEXTO_EJEMPLO)
        self._actualizar_lab()

    def _programar_lab(self):
        if self._pendiente_lab:
            self.root.after_cancel(self._pendiente_lab)
        self._pendiente_lab = self.root.after(250, self._actualizar_lab)

    def _actualizar_lab(self):
        self._pendiente_lab = None
        texto = self.lab_entrada.get("1.0", "end-1c")
        if not texto.strip():
            self.lbl_lab.config(text="")
            for panel in self.lab_paneles:
                poner_texto(panel, [("Escribe algo arriba para verlo transformado en tiempo real.", "muted")])
            return
        usar_topn, top_n = self.use_topn_var.get(), self._leer_topn()
        try:
            palabras = self.llamar('normalizar_texto', texto, traza=False)
            mini = {}
            if usar_topn:
                self.llamar('procesar_url_en_indice_top_n', "texto://prueba", texto, mini, top_n, traza=False)
            else:
                self.llamar('procesar_url_en_indice', "texto://prueba", texto, mini, traza=False)
        except ErrorAlumno as error:
            for panel in self.lab_paneles:
                poner_texto(panel, [(f"✖ {error}", "error")])
            return
        contador = Counter(palabras)
        self.lbl_lab.config(text=f"{fmt_num(len(texto))} caracteres → {fmt_num(len(palabras))} palabras "
                                 f"({fmt_num(len(contador))} distintas)")
        poner_texto(self.lab_paneles[0], [str(palabras)] if palabras else [("(lista vacía)", "muted")])
        poner_texto(self.lab_paneles[1], [f"{p:<16} × {c}\n" for p, c in contador.most_common(40)])
        lineas = [f"{p!r}: {sorted(u)}\n" for p, u in sorted(mini.items())[:40]]
        if len(mini) > 40:
            lineas.append(f"… y {fmt_num(len(mini) - 40)} palabras más\n")
        encabezado = (f"Modo top-N (N={top_n}): {len(mini)} palabras\n\n" if usar_topn else f"{len(mini)} palabras\n\n")
        poner_texto(self.lab_paneles[2], [(encabezado, "negrita")] + lineas)

    def _lab_indexar(self):
        texto = self.lab_entrada.get("1.0", "end-1c")
        if not texto.strip():
            return
        self.num_prueba += 1
        url = f"texto://mi-prueba-{self.num_prueba}"
        try:
            self.procesar_pagina(url, texto, self.use_topn_var.get(), self._leer_topn())
        except ErrorAlumno as error:
            self.avisar_error(error)
            return
        self.notebook.select(self.tab_indice)
        self.trazar_gui(f"Texto indexado como {url}")

    # ------------------------------------------------------------------ cierre
    def on_closing(self):
        if self.trabajo and not self.trabajo.terminado:
            self.trabajo.cancelado.set()
        self.root.destroy()


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    app = BuscadorApp(root)
    root.mainloop()
