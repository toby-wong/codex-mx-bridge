-- Direct iTerm panes only. No keystrokes, command execution, or Herdr pane selection.
on run argv
    set targetId to item 1 of argv
    set targetTty to item 2 of argv
    tell application "iTerm2"
        repeat with win in windows
            repeat with tabRef in tabs of win
                repeat with sess in sessions of tabRef
                    if (targetId is not "" and (unique id of sess) is targetId) or (targetTty is not "" and (tty of sess) is targetTty) then
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
