# dsyed
# 08/09/23
# This is a simple prototype for the Schedule application

from datetime import datetime, timedelta
import dateutil.parser as dparser
import pickle
import os

#----- VARIABLES -----
# -- Constants --
MAX_GROUP_TASKS = 2
NULL_VAL = 1000    # For filler, starter entries in taskHistory arrays
# Task type markers:
BINARY = 0
CONTINUOUS = 1
MEASURED = 2
# Task history binary yes/no indicator for previous integer (NOTE: May not need these)
YES = 1
NO = 0
# Value for tracking excluded tasks in Continuous task history (NOTE: May not need these)
EXCLUDED_CONT = 0.5

# -- Hardcoded data --
class Group:    # Class that holds all data for each group
    def __init__(self, name, timing1, timing2, timing3, currDate):
        self.name = name
        self.taskPtrs = []  # NOTE: May have to turn this into dict to make deleting tasks easier
        self.timing = [timing1, timing2, timing3]   # For day, week, and month respectively.
                                                    # If value is greater than 0, then specific 
                                                    #   days/weeks/months have been chosen based on bit 
                                                    #   positions.
                                                    # If the value is 0, it is included on every day/week/month.
                                                    # If the value is less than 0, then it is included after a
                                                    #   specific number of days/weeks/months based on abs(value).
        self.included = currDate    # The last active date this group was included in

class Task:     # Class that holds all data for each task
    def __init__(self, name, ttype, group, maxCont=-1, displayOpt=0):
        self.keyName = name
        self.ttype = ttype
        self.groupPtrs = [group]
        self.maxCont = maxCont  # If applicable (only for CONTINUOUS task)
        self.description = ""
        self.displayOpt = displayOpt    # NOTE: Might take this out (only needs type)

class OTTask:   # Class that holds all data for each one-time task
    def __init__(self, name, ttype, maxCont=-1):
        self.name = name
        self.ttype = ttype
        self.value = 0
        self.maxCont = maxCont  # If applicable (only for CONTINUOUS task)

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
            if t not in tasksToday:
                tasksToday[t] = 0

    return

# Manipulates the display for today's entry
def dispEntry() -> None:
    indent = "    "

    # No tasks for today
    if len(tasksToday) == 0 and len(oneTimes) == 0:
        print("You have no tasks for today.\n")
        return

    # Print out today's recurring tasks in the correct format
    print("RECURRING TASKS:")
    for t in tasksToday:
        if allTasks[t].ttype == BINARY:
            taskStatus = "NOT COMPLETED"
            if tasksToday[t]:
                taskStatus = "COMPLETED"
            print(indent + allTasks[t].keyName + ": " + taskStatus)
        elif allTasks[t].ttype == CONTINUOUS:
            if tasksToday[t] == allTasks[t].maxCont:
                print(indent + allTasks[t].keyName + ": COMPLETED")
            else:
                print(indent + allTasks[t].keyName + ": " + str(tasksToday[t]) + "/" +
                      str(allTasks[t].maxCont))
        elif allTasks[t].ttype == MEASURED:
            print(indent + allTasks[t].keyName + ": " + str(tasksToday[t]))

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
        if t in checkedTasks:
            continue
        checkedTasks[t] = True

        # Add marker for exclusion
        if allTasks[t].ttype == BINARY:
            if taskHistory[t][-2] < 0:
                taskHistory[t][-2] -= 1
            else:
                taskHistory[t].append(taskHistory[t][-1])
                taskHistory[t][-1] = -1
        elif allTasks[t].ttype == CONTINUOUS or allTasks[t].ttype == MEASURED:
            if isinstance(taskHistory[t][-1], float):
                taskHistory[t][-1] += 1
            else:
                taskHistory[t].append(EXCLUDED_CONT)

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
                if t in checkedTasks:
                    continue
                checkedTasks[t] = True

                # Mark task as incomplete in task history
                if allTasks[t].ttype == BINARY:
                    # Again accounting for excluded entries
                    addPtr = -2
                    if taskHistory[t][-2] < 0:
                        addPtr = -3

                    if taskHistory[t][-1] == 0:
                        taskHistory[t][addPtr] += 1
                    else:
                        taskHistory[t][-1] = 1
                        taskHistory[t].append(0)
                elif allTasks[t].ttype == CONTINUOUS or allTasks[t].ttype == MEASURED:
                    if taskHistory[t][-1] < 0:
                        if taskHistory[t][-2] == 0:
                            taskHistory[t][-1] -= 1
                        else:
                            taskHistory[t].append(0)
                    else:
                        if taskHistory[t][-1] == 0:
                            taskHistory[t].append(-2)
                        else:
                            taskHistory[t].append(0)

        # Go through the groups and add relevant tasks (for excluded)
        checkedTasks = {}
        for group in allGroups:
            if checkedGroups[group.name]:
                continue

            for t in group.taskPtrs:
                if t in checkedTasks:
                    continue
                checkedTasks[t] = True

                # Mark as excluded in task history
                if allTasks[t].ttype == BINARY:
                    if taskHistory[t][-2] < 0:
                        taskHistory[t][-2] -= 1
                    else:
                        taskHistory[t].append(taskHistory[t][-1])
                        taskHistory[t][-1] = -1
                elif allTasks[t].ttype == CONTINUOUS or allTasks[t].ttype == MEASURED:
                    if isinstance(taskHistory[t][-1], float):
                        taskHistory[t][-1] += 1
                    else:
                        taskHistory[t].append(EXCLUDED_CONT)

        # Update the last date by a day until it reaches the current date
        newLastDate = newLastDate + timedelta(days=1)

    return newLastDate

# Add a new task
def addTask(currDate) -> None:
    # Get general info for this new task
    nameExists = True
    taskName = ""
    while nameExists == True:
        taskName = input("What name do you want for this task? (Don't choose an existing name)\n")
        if taskName not in allTasks:
            nameExists = False

    taskType = -1
    thisMaxCont = -1
    while (taskType < 0) or (taskType > MAX_GROUP_TASKS):
        taskType = input("What type of task is this? ('0' for Binary, '1' for Continuous, and '2' for Measured)\n")
        taskType = int(taskType)
    if taskType == CONTINUOUS:
        thisMaxCont = int(input("What is the max count value for this task?\n"))
    isOTT = input("Is this a one-time task? (Answer 'Y' for Yes and 'N' for No)\n")

    # Create OTT if applicable
    if isOTT == 'Y':
        oneTimes.append(OTTask(taskName, taskType, thisMaxCont))
        return

    # Check if an older, deleted task with that name is already in taskHistory
    if taskName in taskHistory:
        print("A task with that name has existed before in Task History.")
        overwrite = input("Would you like to overwrite that history completely with this new task?\n")
        if overwrite == 'N':
            return

    # Create general task otherwise
    addToGroup = False
    addToGroup = int(input("Would you like add this to a group? Otherwise a new group will be created. (1 for Yes, 0 for No)\n"))
    if addToGroup == True:
        if len(allGroups) == 0:
            print("You have no groups to add to.\n")
            return

        print("All Groups:\n")
        for i in range(0, len(allGroups)):
            print("    " + str(i) + ":", allGroups[i].name, "\n")

        groupID = -1
        while (groupID < 0) or (groupID >= len(allGroups)):
            groupID = int(input("Which group would you like to add it to? (Enter the value)\n"))
        allGroups[groupID].taskPtrs.append(taskName)
        allTasks[taskName] = Task(taskName, taskType, allGroups[groupID].name, thisMaxCont)
        taskHistory[taskName] = [NULL_VAL, NULL_VAL, NULL_VAL]

        return

    # Create group with task if applicable (no existing group was chosen above)
    nameExists = True
    groupName = ""
    while nameExists == True:
        groupName = input("What name do you want for this group? (Don't choose an existing name)\n")
        nameExists = False
        for grp in allGroups:
            if groupName == grp.name:
                nameExists = True

    print("Now you need to set the timing of this group task for the day, week, and month.")
    print("Enter a 0 for this task to happen every time period, a positive number for specific points in this time period (represented by bits), or a negative number to skip a certain time period value.")
    dayTiming = -7
    weekTiming = -4
    monthTiming = -12
    while (dayTiming < -6) or (dayTiming > 127):
        dayTiming = int(input("Timing for day:\n"))
    while (weekTiming < -3) or (weekTiming > 4503599627370495):
        weekTiming = int(input("Timing for week:\n"))
    while (monthTiming < -11) or (monthTiming > 4095):
        monthTiming = int(input("Timing for month:\n"))

    allGroups.append(Group(groupName, dayTiming, weekTiming, monthTiming, currDate))
    allGroups[-1].taskPtrs.append(taskName)
    allTasks[taskName] = Task(taskName, taskType, groupName, thisMaxCont)
    tasksToday[taskName] = 0
    taskHistory[taskName] = [NULL_VAL, NULL_VAL, NULL_VAL]

    return

# Delete an existing task
def deleteTask() -> None:
    deleteName = input("Enter the name of the task you would like to delete.\n")
    if deleteName not in allTasks:
        print("This task does not exist. Try again.")
        return

    for grp in allTasks[deleteName].groupPtrs:
        if len(allGroups[grp].taskPtrs) <= 1:
            print("This will delete the group known as:", grp)
            deleteGroup = input("Is that okay?\n")

            # There exists a group that should still exist, so end operation
            if deleteGroup == "N":
                return

    for grp in allTasks[deleteName].groupPtrs:
        del allGroups[grp]
    del allTasks[deleteName]

    return

# Remove an existing task from an existing group
def removeFromGroup() -> None:
    removeGroup = input("Enter the name of the group you want to remove a task from.\n")
    if removeGroup not in allGroups:
        print("This group does not exist. Try again.")
        return

    removeName = input("Enter the name of the task you would like to remove.\n")
    if removeName not in allGroups[removeGroup].taskPtrs:
        print("This task is not in this group. Try again.")
        return

    # Check if this is the only group this task is in. If so, redirect to deleteTask function.
    if len(allTasks[removeName].groupPtrs) <= 1:
        print("This will delete the task, since it exists in only one group.")
        print("Use the 'Delete Task' function instead.")
        return

    if len(allGroups[removeGroup].taskPtrs) <= 1:
        deleteGroup = input("This will delete the group. Is that okay?\n")
        if deleteGroup == "Y":
            del allGroups[removeGroup]
        else:
            return

    # TODO: Remove task from *allGroups[removeGroup].taskPtrs*. Difficult since it is an array.
    return

# Mark the progress on one of today's tasks
def markTask() -> None:
    # TODO
    return

# Save the data before the program ends using Pickle
def saveData() -> None:
    global otherVars

    with open("taskhistory.pkl", 'wb') as f:
        pickle.dump(taskHistory, f)
    with open("alltasks.pkl", 'wb') as f:
        pickle.dump(allTasks, f)
    with open("onetimetasks.pkl", 'wb') as f:
        pickle.dump(oneTimeTasks, f)
    with open("currgraph.pkl", 'wb') as f:
        pickle.dump(currGraph, f)
    with open("taskstoday.pkl", 'wb') as f:
        pickle.dump(tasksToday, f)

    otherVars = {"lastdate": lastDate, "othermedia": otherMedia, "allgroups": allGroups, "onetimes": oneTimes}
    with open("othervars.pkl", 'wb') as f:
        pickle.dump(otherVars, f)

    return

# Retrieve all the stored data from Pickle file
# NOTE: This function assumes the files exist
def loadData() -> None:
    global taskHistory, allTasks, oneTimeTasks, currGraph, tasksToday, otherVars, lastDate, otherMedia, \
            allGroups, oneTimes

    f = open("taskhistory.pkl", "rb")
    taskHistory = pickle.load(f)
    f.close()
    f = open("alltasks.pkl", "rb")
    allTasks = pickle.load(f)
    f.close()
    f = open("onetimetasks.pkl", "rb")
    oneTimeTasks = pickle.load(f)
    f.close()
    f = open("currgraph.pkl", "rb")
    currGraph = pickle.load(f)
    f.close()
    f = open("taskstoday.pkl", "rb")
    tasksToday = pickle.load(f)
    f.close()

    f = open("othervars.pkl", "rb")
    otherVars = pickle.load(f)
    f.close()
    lastDate = otherVars["lastdate"]
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
    if not os.path.isfile("taskhistory.pkl") or not os.access("taskhistory.pkl", os.R_OK):
        print("HERE")
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
                "t": "Today's Entry",
                "a": "Add a Task",
                "c": "Mark a Task's Progress",
                "d": "Delete a Task,"
                "r": "Remove a Task from a Group"
                "x": "Debug"}
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
            addTask(currDate)
        elif choice == "c":     # Mark that a task (or part of it) has been completed
            markTask()
        elif choice == "d":     # Delete a task
            deleteTask()
        elif choice == "r":
            removeFromGroup()   # Removes a task from a group
        elif choice == "x":
            for t in tasksToday:
                print(allTasks[t].ttype)
            print(allTasks)
    # Save the data
    saveData()

    print("The program has ended.")
