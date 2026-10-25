-- Select the outer iTerm pane; Herdr navigation is handled by its socket API.
on run argv
    set targetId to item 1 of argv
    set targetTty to item 2 of argv
    tell application "iTerm2"
        repeat with win in windows
            repeat with tabRef in tabs of win
                repeat with sess in sessions of tabRef
                    if (targetId is not "" and (unique id of sess) is targetId) or (targetId is "" and targetTty is not "" and (tty of sess) is targetTty) then
                        if (count of argv) > 2 then
                            if item 3 of argv is "check" then return "available"
                        end if
                        select win
                        select tabRef
                        select sess
                        activate
                        return "focused"
                    end if
                end repeat
            end repeat
        end repeat
    end tell
    error "Original iTerm session is no longer open" number 1
end run
