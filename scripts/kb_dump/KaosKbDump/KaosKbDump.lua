-- KaosKbDump: a developer-only addon for wow-tools (see scripts/kb_dump/README.md). It never ships with the app.
-- /kbdump records every CVar the client knows (help text, console category, default, current value, where it is
-- stored and its lock flags) and every slash command, into the KaosKbDumpDB SavedVariables. The game writes that
-- file at logout or /reload; scripts/refresh_kb.py turns it into wowtools/kb/. No libraries, no events: nothing
-- runs until /kbdump is typed.

local SELF_KEY = "KAOSKBDUMP"

-- Enum.ConsoleCategory number -> its name ("Graphics", "Game" ...); an older client without the enum keeps numbers.
local function categoryNames()
    local names = {}
    local enum = Enum and Enum.ConsoleCategory
    if type(enum) == "table" then
        for name, number in pairs(enum) do
            names[number] = name
        end
    end
    return names
end

local function isCVar(info)
    local cvarType = Enum and Enum.ConsoleCommandType and Enum.ConsoleCommandType.Cvar
    return info.commandType == (cvarType or 0)
end

local function flag(value)
    return value and true or false
end

local function dumpCVars()
    local getAll = (C_Console and C_Console.GetAllCommands) or ConsoleGetAllCommands
    if not getAll then
        return nil, 0
    end
    local getInfo = C_CVar and C_CVar.GetCVarInfo
    local categories = categoryNames()
    local cvars, count = {}, 0
    for _, info in ipairs(getAll() or {}) do
        local name = info.command
        if type(name) == "string" and isCVar(info) then
            local entry = { help = info.help, category = categories[info.category] or info.category }
            local ok, value, default, account, character, locked, secure, readonly = pcall(getInfo, name)
            if ok then
                entry.value, entry.default = value, default
                entry.account, entry.character = flag(account), flag(character)
                entry.locked, entry.secure, entry.readonly = flag(locked), flag(secure), flag(readonly)
            end
            cvars[name] = entry
            count = count + 1
        end
    end
    return cvars, count
end

-- "/cast" -> "CAST", from the SLASH_<KEY><n> globals, then any hash_SlashCmdList entry they missed (its key found
-- by its handler in SlashCmdList). When two keys claim one slash, the alphabetically first wins, so reruns agree.
local function dumpCommands()
    local commands, count = {}, 0
    local function add(slash, key)
        if type(slash) ~= "string" or slash:sub(1, 1) ~= "/" or key == SELF_KEY then
            return
        end
        slash = slash:lower()
        if commands[slash] == nil then
            count = count + 1
        end
        if commands[slash] == nil or key < commands[slash] then
            commands[slash] = key
        end
    end
    for name, slash in pairs(_G) do
        if type(name) == "string" and type(slash) == "string" then
            local key = name:match("^SLASH_(.-)%d+$")
            if key and key ~= "" then
                add(slash, key)
            end
        end
    end
    local keyOf = {}
    for key, handler in pairs(SlashCmdList or {}) do
        keyOf[handler] = key
    end
    for slash, handler in pairs(hash_SlashCmdList or {}) do
        if type(slash) == "string" and commands[slash:lower()] == nil and keyOf[handler] then
            add(slash, keyOf[handler])
        end
    end
    return commands, count
end

local function run()
    local version, build = GetBuildInfo()
    local cvars, cvarCount = dumpCVars()
    if not cvars then
        print("KaosKbDump: this client has no C_Console.GetAllCommands; nothing recorded.")
        return
    end
    local commands, commandCount = dumpCommands()
    KaosKbDumpDB = {
        build = version .. " " .. build,
        flavor = WOW_PROJECT_ID,
        locale = GetLocale and GetLocale() or nil,
        when = date("%Y-%m-%d %H:%M:%S"),
        cvars = cvars,
        commands = commands,
    }
    print(string.format("KaosKbDump: recorded %d CVars and %d slash commands for build %s %s. "
        .. "Log out (or /reload) so the game writes the file.", cvarCount, commandCount, version, build))
end

SLASH_KAOSKBDUMP1 = "/kbdump"
SlashCmdList[SELF_KEY] = run
