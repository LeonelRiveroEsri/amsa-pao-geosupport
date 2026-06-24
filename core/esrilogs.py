from pathlib import Path
import os
import pandas as pd
import sys
import traceback
import unicodedata
import re
from typing import Optional, Tuple
import re
import shutil

# === Rich opcional con auto-instalación segura ===
import os, sys, subprocess
RICH_OK = False

# Permite desactivar por variable de entorno si hiciera falta:
#   set ESRILOGS_RICH=0               -> desactiva uso de rich
#   set ESRILOGS_RICH_AUTOINSTALL=0   -> no intenta instalar automáticamente
_USE_RICH = os.environ.get("ESRILOGS_RICH", "1") != "0"
_AUTO = os.environ.get("ESRILOGS_RICH_AUTOINSTALL", "1") != "0"

if _USE_RICH:
    try:
        from rich.console import Console
        from rich.theme import Theme
        from rich.highlighter import RegexHighlighter
        from rich.markup import escape
        RICH_OK = True
    except Exception:
        if _AUTO:
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "rich>=13.7.0", "--quiet"]
                )
                from rich.console import Console
                from rich.theme import Theme
                from rich.highlighter import RegexHighlighter
                from rich.markup import escape
                RICH_OK = True
            except Exception:
                RICH_OK = False
else:
    RICH_OK = False

# Consola “dummy” si no hay rich (no rompe nada)
class _DummyConsole:
    def print(self, *args, **kwargs):
        print(*args)

if not RICH_OK:
    Console = _DummyConsole
    Theme = object
    RegexHighlighter = object
    def escape(s): return s

TS_PATTERNS = [
    # "07/10/2025, 14:55:31"
    (re.compile(r"(\d{2}/\d{2}/\d{4}),\s*(\d{2}:\d{2}:\d{2})"), "%d/%m/%Y", "%H:%M:%S"),
    # agrega otros si usas otro formato (ej. 2025-10-07 14:55:31)
]

TS_RX = re.compile(r"(\d{2}/\d{2}/\d{4}),\s*(\d{2}:\d{2}:\d{2})")
_theme = Theme({
    "base": "#E6E3DD",
    "time": "dim #9AA5B1",
    "sep": "dim #6B7280",
    "lvl.info": "#7AD8E6",
    "lvl.warn": "#FFD173",
    "lvl.error": "#FF6E6E",
    "kw.start": "#7AAEF7",
    "kw.exec": "#79D2A6",
    "kw.end": "#9CC2FA",
    "kw.close": "#E9C46A",
    "num": "#9FE7F0",
})

class _LogHighlighter(RegexHighlighter):
    highlights = [
        r"(?P<time>\b\d{2}/\d{2}/\d{4},\s*\d{2}:\d{2}:\d{2}\b)",
        r"(?P<num>\b\d+\b)",
        r"(?P<kw_start>\bSTART\b)",
        r"(?P<kw_exec>\bEXECUTION\b|\bFUNCTION\b)",
        r"(?P<kw_end>\bEND\b)",
        r"(?P<kw_close>\bCLOSING\b)",
        r"(?P<sep>-->|-)",
    ]

_hl = _LogHighlighter()
_console = Console(theme=_theme, highlighter=_hl)  # <-- aquí va el highlighter

def _lvl_style(prefix: str) -> str:
    if prefix.startswith("ERROR"):
        return "[lvl.error]ERROR -[/]"
    if prefix.startswith("WARN"):
        return "[lvl.warn]WARN -[/]"
    return "[lvl.info]INFO -[/]"

def _pad(label: str, width: int) -> str:
    return (label + " " * width)[:width]

def _print_console(line: str):
    try:
        prefix, rest = line.split(" - ", 1)
        fecha, rest2 = rest.split(" - ", 1)
        etapa, msg = rest2.split(" - ", 1)
    except ValueError:
        _console.print(f"[base]{line}[/base]")
        return

    etapa_clean = etapa.strip()
    etapa_fixed = _pad(etapa_clean, 9)

    lvl_markup = _lvl_style(prefix)
    etapa_style = {
        "START": "kw.start",
        "EXECUTION": "kw.exec",
        "FUNCTION": "kw.exec",
        "END": "kw.end",
        "CLOSING": "kw.close",
    }.get(etapa_clean, "base")

    # Escapa el cuerpo por si trae [] u otros caracteres de markup
    msg_esc = escape(msg)

    out = (
        f"{lvl_markup} "
        f"[time]{fecha}[/time] "
        f"[sep]-[/sep] "
        f"[{etapa_style}]{etapa_fixed}[/{etapa_style}] "
        f"[sep]-[/sep] "
        f"[base]{msg_esc}[/base]"
    )

    _console.print(out)   # <-- sin highlighter=

def rename_logs(old_file_name):
    tiempo = pd.Timestamp.today().strftime("%d-%m-%Y %H-%M-%S")   
    name_general_old = Path(old_file_name).stem
    old_folder = Path(old_file_name).parent / "Old" / name_general_old
    new_file_name = old_folder / f"{name_general_old}-{tiempo}.log"

    old_folder.mkdir(parents=True, exist_ok=True)

    if os.path.exists(old_file_name):
        os.rename(old_file_name, new_file_name)

def _parse_dt(line: str) -> Optional[pd.Timestamp]:
    """
    Extrae datetime desde una línea con formato:
      'dd/mm/yyyy, HH:MM:SS'
    """
    m = TS_RX.search(line)
    if not m:
        return None
    return pd.to_datetime(f"{m.group(1)} {m.group(2)}", format="%d/%m/%Y %H:%M:%S")

def _read_text_robust(path_log: Path) -> str:
    """Lee el archivo intentando varios encodings."""
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return path_log.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path_log.read_text(encoding="utf-8", errors="replace")

def obtener_primera_fecha_log(path_log: str) -> Optional[pd.Timestamp]:
    """
    Busca la PRIMERA fecha/hora parseable dentro del log.
    Ideal para medir antigüedad real del contenido (no mtime).
    """
    p = Path(path_log)
    if not p.exists():
        return None

    text = _read_text_robust(p)
    for line in text.splitlines():
        dt = _parse_dt(line)
        if dt:
            return dt
    return None

def log_excede_antiguedad(path_log: Path, max_age_days: int, now: Optional[pd.Timestamp] = None) -> bool:
    """
    True si el log tiene una primera fecha y supera max_age_days respecto a 'now'.
    Fallback: si no hay fecha parseable, usa mtime del archivo.
    """
    if max_age_days is None:
        return False

    if now is None:
        now = pd.Timestamp.now()

    first_dt = obtener_primera_fecha_log(str(path_log))
    if first_dt is not None:
        age = now - first_dt
        return age >= pd.Timedelta(days=int(max_age_days))

    # Fallback por si el log no tiene timestamps reconocibles
    try:
        mtime = pd.Timestamp.fromtimestamp(path_log.stat().st_mtime)
        age = now - mtime
        return age >= pd.Timedelta(days=int(max_age_days))
    except Exception:
        return False

def _wipe_log_file(path_log: Path):
    """Elimina el log actual (sin mover a Old)."""
    try:
        if path_log.exists():
            path_log.unlink()
    except Exception:
        # fallback por si está bloqueado en Windows
        try:
            with open(path_log, "w", encoding="utf-8"):
                pass
        except Exception:
            pass
        
def rename_logs(old_file_name):
    tiempo = pd.Timestamp.today().strftime("%d-%m-%Y %H-%M-%S")
    old_file_name = Path(old_file_name)

    name_general_old = old_file_name.stem
    old_folder = old_file_name.parent / "Old" / name_general_old
    new_file_name = old_folder / f"{name_general_old}-{tiempo}.log"

    old_folder.mkdir(parents=True, exist_ok=True)

    if old_file_name.exists():
        os.rename(old_file_name, new_file_name)
        
def obtener_horas_inicio_fin(path_log: str):
    # lectura robusta por encoding
    text = None
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path_log, "r", encoding=enc) as f:
                text = f.read()
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        with open(path_log, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

    hora_ini = None
    hora_fin = None
    for line in reversed(text.splitlines()):
        if hora_fin is None and (" END " in line or " - END - " in line or "Terminado" in line):
            dt = _parse_dt(line)
            if dt: hora_fin = dt
        elif hora_ini is None and (" START " in line or " - START - " in line or "BEGIN" in line):
            dt = _parse_dt(line)
            if dt: hora_ini = dt
        if hora_ini and hora_fin:
            break

    return (hora_ini, hora_fin) if (hora_ini and hora_fin) else None

def _format_td(td) -> str:
    total = int(td.total_seconds())
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def duracion_ejecucion(path_log: str):
    res = obtener_horas_inicio_fin(path_log)
    if not res:
        return None
    ini, fin = res
    return fin - ini

def write(text_F, tipo_p, etapa, pCadena, *, colored_terminal=True):
    tiempo = pd.Timestamp.now().strftime("%d/%m/%Y, %H:%M:%S - ")
    mensaje = f"{tipo_p}{tiempo}{etapa}{pCadena}\n"
    msg = f"{tipo_p}{tiempo}{etapa}{pCadena}"

    # Archivo (siempre limpio)
    with open(text_F, 'a', encoding='utf-8') as text_file:
        text_file.write(mensaje)

    # Consola (sin ANSI): Rich
    if colored_terminal:
        _print_console(msg)
    else:
        print(msg)

def _cleanup_old_folders(path_log: Path):
    """
    Elimina Old/<stem>/ y luego Old/ si queda vacío.
    path_log: .../Logs/mi_log.log
    """
    try:
        stem = path_log.stem
        old_root = path_log.parent / "Old"          # .../Logs/Old
        old_leaf = old_root / stem                  # .../Logs/Old/mi_log

        if old_leaf.exists():
            shutil.rmtree(old_leaf, ignore_errors=True)

        # Si Old/ existe y quedó vacío, lo borra
        if old_root.exists() and not any(old_root.iterdir()):
            old_root.rmdir()
    except Exception:
        pass
    
class Logfile:
    def __init__(
        self,
        file_name,
        log_path=None,
        overwrite=False,
        max_age_days: Optional[int] = None,
        rotate_mode: str = "archive",  # <-- NUEVO: "archive" | "wipe"
    ):
        self.log_path = Path(log_path) / "Logs" if log_path else Path(__file__).parents[1] / "Logs"
        self.file_name = self.log_path / f"{file_name}.log"
        self.log_path.mkdir(parents=True, exist_ok=True)

        rotate_mode = (rotate_mode or "archive").strip().lower()
        if rotate_mode not in ("archive", "wipe"):
            rotate_mode = "archive"

        # 1) overwrite manual
        if overwrite:
            if rotate_mode == "wipe":
                _wipe_log_file(self.file_name)
                _cleanup_old_folders(self.file_name)   # <-- NUEVO
            else:
                rename_logs(self.file_name)

        # 2) rotación por antigüedad
        elif max_age_days is not None and self.file_name.exists():
            if log_excede_antiguedad(self.file_name, int(max_age_days)):
                if rotate_mode == "wipe":
                    _wipe_log_file(self.file_name)
                    _cleanup_old_folders(self.file_name)  # <-- NUEVO
                else:
                    rename_logs(self.file_name)

        # 3) separador inicial
        with open(self.file_name, "a", encoding="utf-8") as text_file:
            separador = "=" * 75 + "\n"
            print(separador.strip())
            text_file.write(separador)


    def start_script(self, pCadena):
        write(self.file_name, 'INFO - ', 'START - ', pCadena)

    def start_funtion(self, pCadena):
        write(self.file_name, 'INFO - ', 'FUNCTION - ', pCadena)

    def start(self, pCadena):
        write(self.file_name, 'INFO - ', '  START - ', pCadena)

    def end(self, pCadena):
        write(self.file_name, 'INFO - ', '  END   - ', pCadena)

    def close(self, pCadena):
        td = duracion_ejecucion(self.file_name)   # td es timedelta o None
        t = f"{pCadena}, Duración: {_format_td(td)}" if td is not None else pCadena
        write(self.file_name, 'INFO - ', ' CLOSING - ', t)

    def error(self, pCadena):
        write(self.file_name, 'ERROR - ', '  EXECUTION - ', pCadena)

    def info(self, pCadena):
        write(self.file_name, 'INFO - ', '  EXECUTION - ', pCadena)
    
    def dataframe(self, df):
        """Guarda un DataFrame en el log manteniendo el formato tabular y sin acentos."""
        if not isinstance(df, pd.DataFrame):
            raise ValueError("El argumento debe ser un DataFrame de pandas.")

        separador = '*' * 75

        # Convertir DataFrame a texto tabular
        contenido = df.to_string(index=True)

        # Eliminar acentos y caracteres especiales
        contenido = unicodedata.normalize('NFKD', contenido).encode('ascii', 'ignore').decode('ascii')

        mensaje = f"\n{separador}\n{contenido}\n{separador}"

        write(self.file_name, 'DATAFRAME - ', '', mensaje) 
    
        
    def warning(self, pCadena):
        write(self.file_name, 'WARN - ', '  WARNING - ', pCadena)

def capturaError(e, name, logs):
    tb = traceback.format_exc()
    logs.error(name)
    logs.error(str(e))
    logs.error(tb)
    
    



