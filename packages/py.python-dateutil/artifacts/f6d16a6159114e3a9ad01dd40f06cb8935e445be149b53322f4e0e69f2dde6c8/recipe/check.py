#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(dateutil, work):
    """Check ISO offsets, leap-month arithmetic, recurrence rules and invalid input."""
    from datetime import datetime,timezone,timedelta
    parser = installed_module('dateutil.parser'); delta = installed_module('dateutil.relativedelta')
    recurrence = installed_module('dateutil.rrule'); zones = installed_module('dateutil.tz')
    parsed = parser.isoparse('2024-02-29T12:30:00+02:00')
    require(parsed.astimezone(timezone.utc) == datetime(2024,2,29,10,30,tzinfo=timezone.utc), 'ISO timezone conversion failed')
    require(datetime(2024,1,31) + delta.relativedelta(months=1) == datetime(2024,2,29), 'Leap-month adjustment failed')
    rule = recurrence.rrule(recurrence.MONTHLY,count=3,dtstart=datetime(2024,1,31))
    require(list(rule) == [datetime(2024,1,31),datetime(2024,3,31),datetime(2024,5,31)], 'Month-end recurrence semantics wrong')
    offset = zones.tzoffset('plus2',7200)
    require(datetime(2024,1,1,tzinfo=offset).utcoffset() == timedelta(hours=2), 'Fixed offset wrong')
    require(zones.gettz('UTC').utcoffset(datetime(2024,1,1)) == timedelta(0), 'UTC zone lookup failed')
    raises(ValueError, lambda: parser.isoparse('2024-02-30T00:00:00'), 'Invalid calendar date accepted')
    raises(ValueError, lambda: delta.relativedelta(months=1.5), 'Fractional calendar months accepted')
    return {'checks':['iso-offset-conversion','leap-month-adjustment','month-end-recurrence','fixed-offset','utc-zone','invalid-date','fractional-month-error']}

if __name__ == "__main__":
    raise SystemExit(main('python-dateutil', 'dateutil', functional))
