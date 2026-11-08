"""Check delivered data against the existing 10:00/17:00 Prague schedule."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PRAGUE = ZoneInfo('Europe/Prague')

def snapshot_freshness(data, now=None):
    now=(now or datetime.now(PRAGUE)).astimezone(PRAGUE)
    due=[(now-timedelta(days=days)).replace(hour=hour,minute=0,second=0,microsecond=0)
         for days in (0,1) for hour in (10,17)]
    expected=max(slot for slot in due if now >= slot+timedelta(minutes=10))
    stamp=str(data.get('last_successful_at') or (data.get('finished_at') if not data.get('error') else '') or '')
    try:
        successful=datetime.strptime(stamp,'%d.%m.%Y %H:%M:%S').replace(tzinfo=PRAGUE)
    except ValueError:
        successful=None
    stale=not successful or successful<expected
    return {'stale':stale,'last_successful_at':stamp,'expected_check_at':expected.strftime('%d.%m.%Y %H:%M'),
            'message':('Neaktuální data. Poslední úspěšná kontrola: '+(stamp or 'není doložena')+
                       '. Výsledek plánované kontroly '+expected.strftime('%d.%m.%Y v %H:%M')+
                       ' nebyl doručen. Starší výsledky zůstávají zobrazené.') if stale else ''}
