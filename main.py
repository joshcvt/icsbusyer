#!/usr/bin/env python

import json
from datetime import datetime, timedelta
from pytz import timezone
import icalendar
import recurring_ical_events
import urllib.request


DEBUG_LEVEL_DEBUG = 1300
DEBUG_LEVEL_INFO = 1200
DEBUG_LEVEL_NO = 1000

DEBUG_LEVEL = DEBUG_LEVEL_DEBUG

DEFAULT_CONFIG_FILE = 'config.json'
DEFAULT_STATE_FILE = 'state.json'
DEFAULT_CALENDAR_REFRESH_INTERVAL_SECONDS = 3600 # 1 hour
DEFAULT_STATUS_REFRESH_INTERVAL_SECONDS = 300
DEFAULT_LOOKFORWARD_DAYS = 3

STATE_STARTED = "STATE_STARTED"
STATE_COMPLETED = "STATE_COMPLETED"

NOW = datetime.now(timezone('US/Eastern')) # gonna want this a lot; will want to config-ize tz eventually

#print("ADDING 12 HOURS BECAUSE TESTING REASONS")
#NOW += timedelta(hours=12)

TIME_SINCE_DAYSTART = NOW - NOW.replace(hour=8, minute=30) 
TIME_SINCE_DAYEND = NOW - NOW.replace(hour=18, minute=0)
TIMEDELTA_ZERO = timedelta(seconds=0)

def debug(str):
    if DEBUG_LEVEL >= DEBUG_LEVEL_DEBUG:
        print(str)

def eventsValidate(events,config=None):
    valids = []
    for ev in events:
        if validateEvent(ev):
            valids.append(ev)
    return valids

def validateEvent(ev,config=None):
    if ev['X-MICROSOFT-CDO-BUSYSTATUS'] == 'BUSY':
        if config and "excludeEventUIDs" in config.keys() and ev['UID'] in config["excludeEventUIDs"]:
            return False
        else:
            return True
    else:
        debug("ev isn't valid!")
        return False

class BusyLight():
    def __init__(self,apiUrl) -> None:
        self.apiUrl = apiUrl
    
    LIGHT_OFF = 0
    LIGHT_GREEN = 1
    LIGHT_RED = 2
    LIGHT_OTHER = 3

    def getStatus(self):
        status = json.load(urllib.request.urlopen(self.apiUrl+"status"))
        if status["status"] == "off":
            return self.LIGHT_OFF
        elif status["blue"] == 0 and status["red"] == 0 and status["green"] > 0:
            return self.LIGHT_GREEN
        elif status["blue"] == 0 and status["green"] == 0 and status["red"] > 0:
            return self.LIGHT_RED
        else:
            return self.LIGHT_OTHER
    
    def setGreen(self):
        urllib.request.urlopen(self.apiUrl+"available")

    def setRed(self):
        debug("setting red")
        urllib.request.urlopen(self.apiUrl+"busy")

    def setOff(self):
        debug("turning off")
        urllib.request.urlopen(self.apiUrl+"off")

def writeState(config,state):
    with open(config['stateFile'], 'w') as f:
        json.dump(state, f)

def loadConfigAndState(configFile=DEFAULT_CONFIG_FILE):

    dirtyConfig = False

    try:
        with open(configFile) as f:
            config = json.load(f)
    except Exception as e:
        config = {}

    if 'stateFile' not in config:
        config['stateFile'] = DEFAULT_STATE_FILE
        dirtyConfig = True
    if 'calendarRefreshIntervalSeconds' not in config:
        config['calendarRefreshIntervalSeconds'] = DEFAULT_CALENDAR_REFRESH_INTERVAL_SECONDS
        dirtyConfig = True
    if dirtyConfig:
        with open(configFile, 'w') as f:
            json.dump(config, f)

    try:
        with open(config['stateFile']) as f:
            state = json.load(f)
    except: # FileNotFoundError, but also if JSON parse fails
        state = {}
    
    return config, state

def loadCalendarAndEvents(config,start_date=(NOW.year,NOW.month,NOW.day),end_date=(NOW.year,NOW.month,NOW.day+DEFAULT_LOOKFORWARD_DAYS)):
    
    # do caching later.
    if 'useLocal' in config and config['useLocal'] == True:
        with open(config['localCalendar'],'r') as f:
            ical_string = f.read()
    else:
        ical_string = urllib.request.urlopen(config["calendar"]).read()
    calendar = icalendar.Calendar.from_ical(ical_string)
    events = recurring_ical_events.of(calendar).between(start_date, end_date)
    debug("calendar had " + str(len(events)) + " events")
    return (calendar, sorted(events,key=lambda event: event["DTSTART"].dt))

def initState():
    return { STATE_STARTED: [], STATE_COMPLETED: [] }

def main():
    config, state = loadConfigAndState()
    if len(state.keys()) < 2:
        state = initState()
    debug(state.keys())
    light = BusyLight(config["apiEndpoint"])

    if TIME_SINCE_DAYEND > TIMEDELTA_ZERO:
        debug("it's after day end")
        if TIME_SINCE_DAYEND < timedelta(seconds=DEFAULT_STATUS_REFRESH_INTERVAL_SECONDS):
            light.setOff()
        quit() # we also outta here

    if TIME_SINCE_DAYSTART < TIMEDELTA_ZERO:
        print ("it's before day start")
        if len(state) > 0:
            state = initState()
            writeState()
        quit() # we outta here
    else:
        debug("within workday, let's go")
        calendar, es = loadCalendarAndEvents(config)
        #if TIME_SINCE_DAYSTART < timedelta(seconds=DEFAULT_STATUS_REFRESH_INTERVAL_SECONDS):
        if light.getStatus() == BusyLight.LIGHT_OFF:
            light.setGreen()
        else:
            debug("light's not off")
    
    rawNowEvents = recurring_ical_events.of(calendar).at(NOW)
    nowEvents = eventsValidate(rawNowEvents)

    if len(nowEvents) == 0:
        if light.getStatus() == BusyLight.LIGHT_RED:
            if len(state[STATE_STARTED]) > 0:
                for uid in state[STATE_STARTED]:
                    state[STATE_COMPLETED].append(uid)
                    state[STATE_STARTED].remove(uid)
                light.setGreen()
            else:
                print ("light's red without an event in state. Leave alone.")
                pass # light was manually set red without an event live. leave it alone
        else:
            debug("no evs live, light's not red, we done")
    else:
        for ev in nowEvents:
            debug("got an ev")
            if ev['UID'] in state[STATE_COMPLETED]:
                debug("ev complete")
                pass
            elif ev['UID'] not in state[STATE_STARTED]:
                debug("ev not in started, adding")
                state[STATE_STARTED].append(ev['UID'])
                light.setRed()
            else:
                debug("ev in started ")
                if light.getStatus() != BusyLight.LIGHT_RED:
                    debug("it's in started but light is manually set to something else -> we should clear this ev to completed")
                    state[STATE_COMPLETED].append(ev['UID'])
                    state[STATE_STARTED].remove(ev['UID'])
                else:
                    debug("ev already started, light red, leaving it")

    writeState(config,state)
    

main()