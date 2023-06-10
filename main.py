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

DEBUG_LEVEL = DEBUG_LEVEL_NO

DEFAULT_CONFIG_FILE = 'config.json'
DEFAULT_STATE_FILE = 'state.json'
DEFAULT_CALENDAR_REFRESH_INTERVAL_SECONDS = 3600 # 1 hour
DEFAULT_STATUS_REFRESH_INTERVAL_SECONDS = 300
DEFAULT_LOOKFORWARD_DAYS = 3

STATE_STARTED = "STATE_STARTED"
STATE_COMPLETED = "STATE_COMPLETED"
STATE_DAYSTARTED = "STATE_DAYSTARTED"
STATE_DAYDATE = "STATE_DAYDATE"

NOW = datetime.now(timezone('US/Eastern')) # gonna want this a lot; will want to config-ize tz eventually

print("SETTING TIME TO 48 HOURS AGO FOR TESTING")
NOW -= timedelta(days=2)

TIME_SINCE_DAYSTART = NOW - NOW.replace(hour=8, minute=30) 
TIME_SINCE_DAYEND = NOW - NOW.replace(hour=18, minute=0)
TIMEDELTA_ZERO = timedelta(seconds=0)

def debug(str):
    if DEBUG_LEVEL >= DEBUG_LEVEL_DEBUG:
        print(str)

def eventsValidate(events,config=None):
    valids = []
    for ev in events:
        if validateEvent(ev,config):
            valids.append(ev)
    return valids

def validateEvent(ev,config=None):
    if ev['X-MICROSOFT-CDO-BUSYSTATUS'] == 'BUSY':
        return config.isEventUIDExcluded(ev)
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
        
    def isOff(self):
        return (self.getStatus() == BusyLight.LIGHT_OFF)
    
    def isGreen(self):
        return (self.getStatus() == BusyLight.LIGHT_GREEN)
    
    def isRed(self):
        return (self.getStatus() == BusyLight.LIGHT_RED)
    
    def isOther(self):
        return(self.getStatus() == BusyLight.LIGHT_OTHER)
    
    def setGreen(self):
        urllib.request.urlopen(self.apiUrl+"available")

    def setRed(self):
        debug("setting red")
        urllib.request.urlopen(self.apiUrl+"busy")

    def setOff(self):
        debug("turning off")
        urllib.request.urlopen(self.apiUrl+"off")

class Config():
    def __init__(self,configFile=DEFAULT_CONFIG_FILE) -> None:
        dirtyConfig = False
        self.jsonDict = {}
        try:
            with open(configFile) as f:
                self.jsonDict = json.load(f)
        except Exception as e:
            # we're just leaving self.jsonDict empty here
            pass

        if 'stateFile' not in self.jsonDict:
            self.jsonDict['stateFile'] = DEFAULT_STATE_FILE
            dirtyConfig = True
        if 'calendarRefreshIntervalSeconds' not in self.jsonDict:
            self.jsonDict['calendarRefreshIntervalSeconds'] = DEFAULT_CALENDAR_REFRESH_INTERVAL_SECONDS
            dirtyConfig = True
        if dirtyConfig:
            with open(configFile, 'w') as f:
                json.dump(self.jsonDict, f)

    def isEventUIDExcluded(self,event):
        eventUID = event['UID']
        if self.jsonDict and ("excludeEventUIDs" in self.jsonDict) and (eventUID in self.jsonDict["excludeEventUIDs"]):
            return False
        else:
            return True
    
    def getStateFile(self):
        return self.jsonDict['stateFile']
    
    def useLocalCalendar(self):
        return (('useLocal' in self.jsonDict) and (self.jsonDict['useLocal'] == True))
    
    def getLocalCalendar(self):
        return self.jsonDict['localCalendar']
    
    def getCalendarURL(self):
        return self.jsonDict['calendar']

    def getAPIEndpoint(self):
        return self.jsonDict['apiEndpoint']

def writeState(config,state):
    with open(config.getStateFile(), 'w') as f:
        json.dump(state, f)

def loadConfigAndState(configFile=DEFAULT_CONFIG_FILE):

    config = Config(configFile)
    try:
        with open(config.getStateFile()) as f:
            state = json.load(f)
    except: # FileNotFoundError, but also if JSON parse fails
        state = {}
    
    return config, state

def loadCalendarAndEvents(config):
    
    start_date = (NOW.year,NOW.month,NOW.day)
    end_stamp = NOW + timedelta(days=DEFAULT_LOOKFORWARD_DAYS)
    end_date = (end_stamp.year, end_stamp.month, end_stamp.day)

    # do caching later.
    if config.useLocalCalendar():
        with open(config.getLocalCalendar(),'r') as f:
            ical_string = f.read()
    else:
        ical_string = urllib.request.urlopen(config.getCalendarURL()).read()
    calendar = icalendar.Calendar.from_ical(ical_string)
    events = recurring_ical_events.of(calendar).between(start_date, end_date)
    debug("calendar had " + str(len(events)) + " events")

    for i in reversed(range(0,len(events))):
        if type(events[i]["DTSTART"].dt).__name__ == 'date':
            del events[i]
            debug("deleted element %i for being a date not datetime" % i)

    return (calendar, sorted(events,key=lambda event: event["DTSTART"].dt))

def initState():
    return { STATE_STARTED: [], STATE_COMPLETED: [], STATE_DAYDATE: NOW.day }

def cleanState(state):
    ks = state.keys()
    return (STATE_COMPLETED in ks and STATE_STARTED in ks and state[STATE_COMPLETED] == [] and state[STATE_STARTED] == [])

def main():
    config, state = loadConfigAndState()
    if len(state.keys()) < 2:   # something's wrong, just clean it
        state = initState()
    debug(state.keys())
    light = BusyLight(config.getAPIEndpoint())

    if (STATE_DAYDATE not in state) or state[STATE_DAYDATE] != NOW.day:
        debug("New day, initing state")
        # either this is the first run of the day or something's broken. either way, clean it out
        state = initState()
    
    if state[STATE_DAYDATE] == NOW.day and STATE_DAYSTARTED in state and light.isOff():
        # we already turned it off once today. don't restart unless manually turned on.
        debug("Manually turned off, exiting")
        quit()

    if TIME_SINCE_DAYEND > TIMEDELTA_ZERO:
        debug("it's after day end")
        debug("default status refresh interval seconds = " + str(DEFAULT_STATUS_REFRESH_INTERVAL_SECONDS))
        debug(str(TIME_SINCE_DAYEND))
        if TIME_SINCE_DAYEND < timedelta(seconds=(DEFAULT_STATUS_REFRESH_INTERVAL_SECONDS+60)):
            # give it that extra 60 seconds because you're probably taking time to load the calendar...
            light.setOff()
        quit() # we also outta here

    if TIME_SINCE_DAYSTART < TIMEDELTA_ZERO:
        debug("it's before day start. ")
        if not cleanState(state):
            state = initState()
            writeState()
        quit() # we outta here
    else:
        debug("within workday, let's go")
        calendar, es = loadCalendarAndEvents(config)
        #if TIME_SINCE_DAYSTART < timedelta(seconds=DEFAULT_STATUS_REFRESH_INTERVAL_SECONDS):
        if light.isOff() and STATE_DAYSTARTED not in state:
            light.setGreen()
            state[STATE_DAYSTARTED] = 1
        else:
            debug("light's not off")
    
    rawNowEvents = recurring_ical_events.of(calendar).at(NOW)
    nowEvents = eventsValidate(rawNowEvents,config)

    if len(nowEvents) == 0:
        if light.isRed():
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
                if light.isRed():
                    debug("ev already started, light red, leaving it")
                else:
                    debug("it's in started but light is manually set to something else -> we should clear this ev to completed")
                    state[STATE_COMPLETED].append(ev['UID'])
                    state[STATE_STARTED].remove(ev['UID'])


    writeState(config,state)
    

main()
