-- KaosKbDump: a developer-only addon for wow-tools (see scripts/kb_dump/README.md). It never ships with the app.
-- /kbdump records every CVar the client knows (help text, console category, default, current value, where it is
-- stored and its lock flags), every slash command and emote (marking the ones an addon registered) and the macro
-- limits, into the KaosKbDumpDB SavedVariables. The game writes that
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
-- by its handler in SlashCmdList), then the emotes ("/dance" -> "EMOTE35", from EMOTE<n>_CMD<m>). A key whose
-- SlashCmdList entry or SLASH_ global an addon set (issecurevariable says tainted) goes into addonCommands, so the
-- refresh can leave it out. When two keys claim one slash, the client's beats an addon's, and between two of a kind
-- the alphabetically first wins, so reruns agree and an addon never hides a client command.
local function dumpCommands()
    local commands, tainted, addon, count = {}, {}, {}, 0
    local secure = issecurevariable or function() return true end
    local function add(slash, key, isAddon)
        if type(slash) ~= "string" or slash:sub(1, 1) ~= "/" or key == SELF_KEY then
            return
        end
        slash = slash:lower()
        local old = commands[slash]
        if old == nil then
            count = count + 1
        end
        if old == nil or (tainted[slash] and not isAddon) or (tainted[slash] == isAddon and key < old) then
            commands[slash], tainted[slash] = key, isAddon
        end
        if isAddon then
            addon[key] = true
        end
    end
    for name, slash in pairs(_G) do
        if type(name) == "string" and type(slash) == "string" then
            local key = name:match("^SLASH_(.-)%d+$")
            local emote = name:match("^(EMOTE%d+)_CMD%d+$")
            if key and key ~= "" then
                add(slash, key, not secure(name) or not secure(SlashCmdList, key))
            elseif emote then
                add(slash, emote, false)
            end
        end
    end
    local keyOf = {}
    for key, handler in pairs(SlashCmdList or {}) do
        keyOf[handler] = key
    end
    for slash, handler in pairs(hash_SlashCmdList or {}) do
        local key = keyOf[handler]
        if type(slash) == "string" and commands[slash:lower()] == nil and key then
            add(slash, key, not secure(SlashCmdList, key))
        end
    end
    return commands, addon, count
end

-- Account macros and macros per character, from the client's MacroConstants (or the older globals).
local function macroLimits()
    local constants = Constants and Constants.MacroConstants or {}
    local account = constants.MAX_ACCOUNT_MACROS or MAX_ACCOUNT_MACROS
    local character = constants.MAX_CHARACTER_MACROS or MAX_CHARACTER_MACROS
    if type(account) == "number" and type(character) == "number" then
        return { account = account, character = character }
    end
end

local function run()
    local version, build = GetBuildInfo()
    local cvars, cvarCount = dumpCVars()
    if not cvars then
        print("KaosKbDump: this client has no C_Console.GetAllCommands; nothing recorded.")
        return
    end
    local commands, addonCommands, commandCount = dumpCommands()
    KaosKbDumpDB = {
        dumpVersion = 2,
        build = version .. " " .. build,
        flavor = WOW_PROJECT_ID,
        locale = GetLocale and GetLocale() or nil,
        when = date("%Y-%m-%d %H:%M:%S"),
        cvars = cvars,
        commands = commands,
        addonCommands = addonCommands,
        macroLimits = macroLimits(),
    }
    print(string.format("KaosKbDump: recorded %d CVars and %d slash commands for build %s %s. "
        .. "Log out (or /reload) so the game writes the file.", cvarCount, commandCount, version, build))
end

SLASH_KAOSKBDUMP1 = "/kbdump"
SlashCmdList[SELF_KEY] = run
