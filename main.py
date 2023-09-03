# dsyed
# 08/09/23
# This is a simple prototype for the Schedule application

from datetime import datetime, timedelta
# TODO: Move code to personal laptop to install this
import dateutil.parser as dparser
import json
import os

#----- VARIABLES -----
# -- Constants --
MAX_GROUP_TASKS = 5
# Task type markers:
BINARY = 0
CONTINUOUS = 1
MEASURED = 2
# Task history binary yes/no indicator for previous integer
YES = 1
NO = 0
# Value for tracking excluded tasks in Continuous task history
EXCLUDED_CONT = 0.5

# -- Hardcoded data --
class Group:    # Class that holds all data for each group
    def __init__(self, name):
        self.name = name
        self.taskPtrs = []
        self.timing = [0, 0, 0]
        self.included = None

class Task:     # Class that holds all data for each task
    def __init__(self, name, ttype, displayOpt, group, maxCont=-1):
        self.keyName = name
        self.ttype = ttype
        self.displayOpt = displayOpt    # NOTE: Might take this out (only needs type)
        self.groupPtrs = [group]
        self.maxCont = maxCont  # If applicable (only for CONTINUOUS task)

class OTTask:   # Class that holds all data for each one-time task
    def __init__(self, name, ttype, maxCont=-1):
        self.name = name
        self.ttype = ttype
        self.value = 0
        self.maxCont = maxCont
        self.completed = False  # NOTE: Might take this out too (only needs type)

# -- Schedule data --
taskHistory = {}    # Keeps track of the complete/incomplete,excluded history of all tasks
lastDate = datetime.today()    # Keeps track of when the app was last opened
otherMedia = []     # Contains list of file names to additional media saved in SQLite
allTasks = {}   # Contains all currently created Task objects that have a group
oneTimeTasks = {}   # Contains all One-Time Task objects that were created since the last archive
allGroups = []  # Contains all the current Group objects
currGraph = {"dateRange": 0,
             "timeScale": 0,
             "addedTasks": [],
             "dispSettings": []}    # Holds info about the most recent graph created
otherVars = {}  # Reference variable just used for loading and saving data

# -- Current display data --
tasksToday = {}     # Key = [task name]; value = [integer for completion]
                    # (Only includes recurring tasks, not one-time tasks)
oneTimes = []   # Holds OTTask objects for the current day


#----- FUNCTIONS -----
# Helper function that checks if the date applies to the group
def isGroupIncluded(groupTiming, dateCheck, dateIncl) -> bool:
    # Check if this group is valid today by going through month, week, and then day
    include = True
    if groupTiming[2] > 0 and include:
        include = (groupTiming[2] >> (12 - dateCheck.date().month)) & 1
    elif groupTiming[2] < 0 and include:
        include = ((dateCheck.date().month - dateIncl.month) % abs(groupTiming[2])) == 0

    weekNum = dateCheck.isocalendar()[1]
    if groupTiming[1] > 0 and include:
        include = (groupTiming[1] >> (52 - weekNum)) & 1
    elif groupTiming[1] < 0 and include:
        include = ((weekNum - dateIncl.isocalendar()[1]) % abs(groupTiming[1])) == 0

    weekDay = dateCheck.weekday()
    if groupTiming[0] > 0 and include:
        include = (groupTiming[0] >> (6 - weekDay)) & 1
    elif groupTiming[0] < 0 and include:
        include = (abs(weekDay - dateIncl.weekday()) % abs(groupTiming[0])) == 0

    return include

# Fill the tasksToday list with the tasks that apply today
def getTodaysTasks(newDate) -> None:
    # Look in groups for repeating tasks
    for group in allGroups:
        # Check if this group is valid
        include = isGroupIncluded(group.timing, newDate, group.included)
        if not include:
            continue
        group.included = newDate    # Update included date for this group

        # Add to today's tasks
        for t in group.taskPtrs:
            if t.keyName not in tasksToday:
                tasksToday[t.keyName] = 0

    return

# Manipulates the display for today's entry
def dispEntry() -> None:
    indent = "    "

    # No tasks for today
    if len(tasksToday) == 0 and lastDate.date() not in oneTimeTasks:
        print("You have no tasks for today.\n")
        return

    # Print out today's recurring tasks in the correct format
    print("RECURRING TASKS:")
    for t in tasksToday:
        if allTasks[t].ttype == BINARY:
            taskStatus = "NOT COMPLETED"
            if tasksToday[t]:
                taskStatus = "COMPLETED"
            print(indent + allTasks[t].name + ": " + taskStatus)
        elif allTasks[t].ttype == CONTINUOUS:
            if tasksToday[t] == allTasks[t].maxCont:
                print(indent + allTasks[t].name + ": COMPLETED")
            else:
                print(indent + allTasks[t].name + ": " + str(tasksToday[t]) + "/" +
                      str(allTasks[t].maxCont))
        elif allTasks[t].ttype == MEASURED:
            print(indent + allTasks[t].name + ": " + str(tasksToday[t]))

    # Print out today's one-time tasks
    print("\nONE-TIME TASKS:")
    for ott in oneTimes:
        if ott.ttype == BINARY:
            taskStatus = "NOT COMPLETED"
            if ott.value:
                taskStatus = "COMPLETED"
            print(indent + ott.name + ": " + taskStatus)
        elif ott.ttype == CONTINUOUS:
            if ott.value == ott.maxCont:
                print(indent + ott.name + ": COMPLETED")
            else:
                print(indent + ott.name + ": " + str(ott.value) + "/" + str(ott.maxCont))
        elif ott.ttype == MEASURED:
            print(indent + ott.name + ": " + str(ott.value))

    print()
    return

# Update all data due to a change in date
def updateTime(newDate) -> datetime:
    # Add the items that were last in tasksToday to taskHistory
    checkedTasks = {}
    for tKey in tasksToday:
        checkedTasks[tKey] = True

        tType = allTasks[tKey].ttype
        if tType == BINARY:  # Binary task
            # This is used to account for the last date having a negative number (exclusion)
            addPtr = -2
            if taskHistory[tKey][-2] < 0:
                addPtr = -3

            if tasksToday[tKey] == taskHistory[tKey][-1]:
                taskHistory[tKey][addPtr] += 1
            else:
                taskHistory[tKey][-1] = 1
                taskHistory[tKey].append(abs(tasksToday[tKey] - 1))
        elif tType == CONTINUOUS or tType == MEASURED:    # Continuous or measured task
            if taskHistory[tKey][-1] < 0:
                if taskHistory[tKey][-2] == tasksToday[tKey]:
                    taskHistory[tKey][-1] -= 1
                else:
                    taskHistory[tKey].append(tasksToday[tKey])
            else:
                if taskHistory[tKey][-1] == tasksToday[tKey]:
                    taskHistory[tKey].append(-2)
                else:
                    taskHistory[tKey].append(tasksToday[tKey])

    # Add tasks from oneTimes (for that day) to oneTimeTasks (storage)
    lastDatesDate = lastDate.date()
    if lastDatesDate not in oneTimeTasks:
        oneTimeTasks[lastDatesDate] = []
    for ott in oneTimes:
        oneTimeTasks[lastDatesDate].append(ott)
    oneTimes.clear()

    # Add tasks from that day that were excluded
    for t in allTasks:
        if t.keyName in checkedTasks:
            continue
        checkedTasks[t.keyName] = True

        # Add marker for exclusion
        if t.ttype == BINARY:
            if taskHistory[t.keyName][-2] < 0:
                taskHistory[t.keyName][-2] -= 1
            else:
                taskHistory[t.keyName].append(taskHistory[t.keyName][-1])
                taskHistory[t.keyName][-1] = -1
        elif t.ttype == CONTINUOUS or t.ttype == MEASURED:
            if isinstance(taskHistory[t.keyName][-1], float):
                taskHistory[t.keyName][-1] += 1
            else:
                taskHistory[t.keyName].append(0.5)

    # Add all incomplete or excluded values for tasks up to today
    # NOTE: The included tasks needed to be marked first, because there may be a task
    #       that is in an included group AND an excluded group. If the excluded group
    #       is processed first, then the task history for that task will be excluded
    #       instead of marked incomplete.
    newLastDate = lastDate + timedelta(days=1)
    while newLastDate < newDate:
        checkedTasks = {}
        checkedGroups = {}
        # Go through groups and add relevant tasks (if included)
        for group in allGroups:
            # Check if the date applies to this group
            include = isGroupIncluded(group.timing, newLastDate, group.included)
            if not include:
                continue
            group.included = newLastDate

            # Mark that this group has been checked
            checkedGroups[group.name] = True
            for t in group.taskPtrs:
                if t.keyName in checkedTasks:
                    continue
                checkedTasks[t.keyName] = True

                # Mark task as incomplete in task history
                if t.ttype == BINARY:
                    # Again accounting for excluded entries
                    addPtr = -2
                    if taskHistory[t.keyName][-2] < 0:
                        addPtr = -3

                    if taskHistory[t.keyName][-1] == 0:
                        taskHistory[t.keyName][addPtr] += 1
                    else:
                        taskHistory[t.keyName][-1] = 1
                        taskHistory[t.keyName].append(0)
                elif t.ttype == CONTINUOUS or t.ttype == MEASURED:
                    if taskHistory[t.keyName][-1] < 0:
                        if taskHistory[t.keyName][-2] == 0:
                            taskHistory[t.keyName][-1] -= 1
                        else:
                            taskHistory[t.keyName].append(0)
                    else:
                        if taskHistory[t.keyName][-1] == 0:
                            taskHistory[t.keyName].append(-2)
                        else:
                            taskHistory[t.keyName].append(0)

        # Go through the groups and add relevant tasks (for excluded)
        checkedTasks = {}
        for group in allGroups:
            if checkedGroups[group.name]:
                continue

            for t in group.taskPtrs:
                if t.keyName in checkedTasks:
                    continue
                checkedTasks[t.keyName] = True

                # Mark as excluded in task history
                if t.ttype == BINARY:
                    if taskHistory[t.keyName][-2] < 0:
                        taskHistory[t.keyName][-2] -= 1
                    else:
                        taskHistory[t.keyName].append(taskHistory[t.keyName][-1])
                        taskHistory[t.keyName][-1] = -1
                elif t.ttype == CONTINUOUS or t.ttype == MEASURED:
                    if isinstance(taskHistory[t.keyName][-1], float):
                        taskHistory[t.keyName][-1] += 1
                    else:
                        taskHistory[t.keyName].append(0.5)

        # Update the last date by a day until it reaches the current date
        newLastDate = lastDate + timedelta(days=1)

    return newLastDate

# Save the data before the program ends using JSON
def saveData() -> None:
    global otherVars

    with open("taskhistory.json", 'w') as f:
        json.dump(taskHistory, f)
    with open("alltasks.json", 'w') as f:
        json.dump(allTasks, f)
    with open("onetimetasks.json", 'w') as f:
        json.dump(oneTimeTasks, f)
    with open("currgraph.json", 'w') as f:
        json.dump(currGraph, f)
    with open("taskstoday.json", 'w') as f:
        json.dump(tasksToday, f)

    otherVars = {"lastdate": lastDate, "othermedia": otherMedia, "allgroups": allGroups, "onetimes": oneTimes}
    with open("othervars.json", 'w') as f:
        json.dump(otherVars, f, default=str)

    return

# Retrieve all the stored data from JSON file
# NOTE: This function assumes the files exist
# TODO: May need to do something to account for pointers
def loadData() -> None:
    global taskHistory, allTasks, oneTimeTasks, currGraph, tasksToday, otherVars, lastDate, otherMedia, \
            allGroups, oneTimes

    f = open("taskhistory.json")
    taskHistory = json.load(f)
    f.close()
    f = open("alltasks.json")
    allTasks = json.load(f)
    f.close()
    f = open("onetimetasks.json")
    oneTimeTasks = json.load(f)
    f.close()
    f = open("currgraph.json")
    currGraph = json.load(f)
    f.close()
    f = open("taskstoday.json")
    tasksToday = json.load(f)
    f.close()

    f = open("othervars.json")
    otherVars = json.load(f)
    f.close()
    lastDate = dparser.parse(otherVars["lastdate"])
    otherMedia = otherVars["othermedia"]
    allGroups = otherVars["allgroups"]
    oneTimes = otherVars["onetimes"]

    return


#----- MAIN -----
# Test the functions for Schedule
if __name__ == '__main__':
    # Random testing
    '''
    test = 0b0101010
    print(datetime.today().weekday())
    print((test >> (6 - datetime.today().weekday())) & 1)
    quit()
    '''

    # Check if this program is being run for the first time before loading data
    # NOTE: Files will already be initialized in app version
    if not os.path.isfile("taskhistory.json") or os.access("taskhistory.json", os.R_OK):
        saveData()
    loadData()

    # Update any data that needs to be updated based on date
    currDate = datetime.today()
    if lastDate.date() < currDate.date():
        lastDate = updateTime(currDate)
        getTodaysTasks(currDate)

    running = True
    while running:
        # Print the menu and receive an input
        menu = {"q": "Quit",
                "t": "Today's Entry"}
        print("Welcome to your schedule app.\nMenu:")
        for key in menu:
            print("   ", key, "-", menu[key])
        choice = input("Which function would you like to try?\n")

        # Choose the appropriate case
        if choice == "q":   # Quit the app
            running = False
        elif choice == "t":     # Show the tasks you have for today
            dispEntry()
        elif choice == "a":     # Create a task
            # TODO: Create this method to add a task
            pass

    # Save the data
    saveData()

    print("The program has ended.")
