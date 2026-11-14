"""停止時刻の計算と、画面・トレイに出す文言を作る関数。

Tk に依存しない純粋な関数だけを置く (tkinter の無い環境でもテストできるように)。
"""
import datetime


# ── 停止時刻の入力 ────────────────────────────────────────────────────────

def _ascii_digits(text: str) -> bool:
    # str.isdigit() は全角数字なども True にするため、半角の 0〜9 だけに限る
    return bool(text) and all('0' <= ch <= '9' for ch in text)


def is_time_input_allowed(proposed: str) -> bool:
    """入力中の値として受け付けるか (Spinbox の validatecommand 用)。

    空欄か、数字2桁まで。入力中は整形しない (カーソル位置がずれて
    「17」の 7 を消して 8 を打つと別の値になる、ということが起きないように)。
    範囲 (0〜23 / 0〜59) の確認と2桁への整形は、確定時 (フォーカスが外れた
    とき・Enter のとき) に normalize_time_field で行う。
    """
    return proposed == '' or (len(proposed) <= 2 and _ascii_digits(proposed))


def time_field_valid(text: str, maxval: int) -> bool:
    """確定してよい値か (数字で 0〜maxval)。"""
    if not _ascii_digits(text):
        return False
    return 0 <= int(text) <= maxval


def normalize_time_field(text: str, maxval: int, fallback: int) -> str:
    """入力を範囲内に丸めて2桁にする。空欄など数字でなければ fallback を使う。"""
    v = int(text) if isinstance(text, str) and _ascii_digits(text) else fallback
    v = max(0, min(maxval, v))
    return f'{v:02d}'


def calc_stop_target(now: datetime.datetime, hour: int, minute: int) -> datetime.datetime:
    """次に来る hour:minute。今日のその時刻を過ぎていれば (ちょうども含む) 翌日。"""
    dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if dt <= now:
        dt += datetime.timedelta(days=1)
    return dt


# ── 文言 ──────────────────────────────────────────────────────────────────

def format_clock(hour: int, minute: int) -> str:
    return f'{hour:02d}:{minute:02d}'


def format_elapsed(seconds: float) -> str:
    sec = max(0, int(seconds))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f'{h:d}:{m:02d}:{s:02d}'


def _day_prefix(target: datetime.datetime, now: datetime.datetime) -> str:
    days = (target.date() - now.date()).days
    if days <= 0:
        return ''
    if days == 1:
        return '明日 '
    return f'{target:%m/%d} '


def stop_note(target: datetime.datetime, now: datetime.datetime) -> str:
    """ON の間に出す「いつ自動で OFF にするか」。今日なら時刻だけ、翌日なら「明日」を付ける。"""
    return f'{_day_prefix(target, now)}{target:%H:%M} に自動で OFF にします'


def stopped_note(target: datetime.datetime) -> str:
    """自動で OFF にした後に出す文言。"""
    return f'{target:%H:%M} に自動で OFF にしました'


def tray_stop_label(target: datetime.datetime | None, now: datetime.datetime,
                    hour: int, minute: int) -> str:
    """トレイメニューの情報行。ON の間は目標時刻 (明日も含む)、OFF なら設定した時刻。"""
    if target is not None:
        return f'{_day_prefix(target, now)}{target:%H:%M} に自動で OFF'
    return f'{format_clock(hour, minute)} に自動で OFF'


def tray_title(running: bool, stop_label: str | None) -> str:
    """トレイのツールチップ。"""
    if not running:
        return "I'm fine - OFF"
    if stop_label:
        return f"I'm fine - ON（{stop_label}）"
    return "I'm fine - ON"


# ── 更新後の再起動 ────────────────────────────────────────────────────────

def parse_iso(text) -> datetime.datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return None


def resume_decision(now: datetime.datetime, stop_target_iso, start_time_iso) -> dict:
    """更新して再起動した後、ON に戻すかどうかを決める。

    更新前に保存した停止目標時刻をすでに過ぎていれば ON にしない
    (再起動が停止時刻をまたいだ場合に、その日だけ自動で OFF にならない、
    ということが起きないように)。経過時間は更新前の開始時刻から引き継ぐ。

    戻り値: {'start': bool, 'stop_target': datetime|None,
             'start_time': datetime|None, 'stopped_at': datetime|None}
    stopped_at は、停止時刻を過ぎていたため ON に戻さなかったときの停止時刻。
    """
    target = parse_iso(stop_target_iso)
    start = parse_iso(start_time_iso)
    if start is not None and start > now:
        start = None
    if target is not None and now >= target:
        return {'start': False, 'stop_target': None, 'start_time': None,
                'stopped_at': target}
    return {'start': True, 'stop_target': target, 'start_time': start,
            'stopped_at': None}
