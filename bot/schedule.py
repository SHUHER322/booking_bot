"""Текст расписания на день для админа (чистая функция — легко тестировать)."""
import html
from collections import defaultdict
from datetime import date

from .db import Booking
from .salon import Salon
from .texts import long_date, rub

MAX_MESSAGE_LEN = 4000  # лимит Telegram — 4096 символов


def build_schedule(day: date, bookings: list[Booking], salon: Salon) -> str:
    """Расписание по мастерам: рабочие часы и записи. Внизу — итог за день."""
    by_master: dict[str, list[Booking]] = defaultdict(list)
    for b in bookings:
        by_master[b.master].append(b)

    lines = [f"📋 <b>Расписание: {long_date(day)}</b>"]
    names = [m.name for m in salon.masters]
    # Мастер мог пропасть из salon.toml, а записи к нему остались — их тоже показываем
    names += [name for name in by_master if name not in names]

    for name in names:
        master = salon.master(name)
        records = sorted(by_master.get(name, []), key=lambda b: b.starts_at)
        if master and not master.works_on(day.weekday()) and not records:
            lines.append(f"\n👤 <b>{html.escape(name)}</b> — выходной")
            continue
        hours = f" · {master.start:%H:%M}–{master.end:%H:%M}" if master else ""
        lines.append(f"\n👤 <b>{html.escape(name)}</b>{hours}")
        if not records:
            lines.append("записей нет")
        for b in records:
            username = f", @{html.escape(b.username)}" if b.username else ""
            lines.append(f"{b.starts_at:%H:%M}–{b.ends_at:%H:%M} {html.escape(b.service)}\n"
                         f"   {html.escape(b.client_name)}, {html.escape(b.client_phone)}{username}")

    if bookings:
        total = sum(b.price for b in bookings)
        lines.append(f"\nИтого: <b>{len(bookings)}</b> зап. на {rub(total)}")
    text = "\n".join(lines)
    if len(text) > MAX_MESSAGE_LEN:
        text = text[:MAX_MESSAGE_LEN].rsplit("\n", 1)[0] + "\n…список обрезан"
    return text
