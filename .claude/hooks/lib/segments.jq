# The normaliser of hook_segments (lib/hook.sh): `shfmt --to-json` gives a real bash syntax tree, and
# this program turns it into the records the guards read.
# Input: the tree on stdin. Arguments: $src (the parsed text, --rawfile), $dir (where it runs), $home,
# $qn (payloads counted so far, the root included) and $max (HOOK_MAX_PAYLOADS).
# Output lines: one record per simple command (dir US body US quoted-bits US words), every field
# escaped by `enc` (hook.sh undoes it), `US payload US dir US text` for each string the caller must
# parse again (`sh -c`, `eval`, a shell's stdin), `US redir US dir US target` for each output redirection,
# `US overflow` past the payload cap, and `US qn US N` last.
# Read as structure: `$(...)`, backticks and process
# substitutions anywhere (also an unquoted heredoc's body, which bash expands) come straight from the
# tree as payloads; `[[ ]]`, `(( ))`, `let` and loop headers give only those payloads.
($src | if utf8bytelength == length then null
        else [0] + ([foreach explode[] as $c (0; . + (if $c < 128 then 1 elif $c < 2048 then 2 elif $c < 65536 then 3 else 4 end); .)] | .[:-1])
        end) as $starts
| def us: "\u001f";
  # The record escapes (hook.sh's `hook_unesc` undoes them): \035 is the escape byte, so a US or RS inside a field
  # never splits it, and a newline is RS.
  def enc: gsub("\u001d"; "\u001de") | gsub("\u001f"; "\u001du") | gsub("\u001e"; "\u001dr") | gsub("\n"; "\u001e");
  # shfmt counts bytes, jq slices code points.
  def cp($b): if $starts == null then $b else ($starts | bsearch($b)) as $i | if $i < 0 then -1 - $i else $i end end;
  def raw: $src[cp(.Pos.Offset):cp(.End.Offset)];
  def unesc: gsub("\\\\(?<c>(.|\n))"; if .c == "\n" then "" else .c end);
  def dqunesc: gsub("\\\\(?<c>(.|\n))"; if .c == "\n" then "" elif (.c | test("^[$`\"\\\\]$")) then .c else "\\" + .c end);
  def num($base): reduce (ascii_downcase | explode[]) as $d (0; . * $base + (if $d >= 97 then $d - 87 else $d - 48 end));
  def ansi: gsub("\\\\(?<c>x[0-9a-fA-F]{1,2}|[0-7]{1,3}|(.|\n))";
    if .c == "n" then "\n" elif .c == "t" then "\t"
    elif (.c | test("^x.")) then [.c[1:] | num(16)] | implode
    elif (.c | test("^[0-7]+$")) then [.c | num(8)] | implode
    else .c end);
  # A parameter expansion or a command substitution may expand to nothing: `e` is the text without it.
  def empty_able: .Type == "ParamExp" or .Type == "CmdSubst";
  def part: if .Type == "Lit" then (.Value | unesc) as $t | {t: $t, quoted: false, e: $t}
    elif .Type == "SglQuoted" then (if .Dollar then .Value | ansi else .Value end) as $t | {t: $t, quoted: true, e: $t}
    elif .Type == "DblQuoted" then [(.Parts // [])[] | if .Type == "Lit" then (.Value | dqunesc) as $t | [$t, $t]
                                                       else raw as $t | [$t, (if empty_able then "" else $t end)] end]
      | {t: (map(.[0]) | add // ""), quoted: true, e: (map(.[1]) | add // "")}
    else raw as $t | {t: $t, quoted: false, e: (if empty_able then "" else $t end)} end;
  def word: [(.Parts // [])[] | part] | {t: (map(.t) | add // ""), q: any(.[]; .quoted), e: (map(.e) | add // "")};
  def declword: if .Array != null then {t: raw, q: false}
    elif .Naked then (if .Value != null then .Value | word else {t: .Name.Value, q: false} end)
    else ((.Value // {}) | word) as $v | (.Name.Value + (if .Append then "+=" else "=" end)) as $n | {t: ($n + $v.t), q: $v.q, e: ($n + $v.e)} end;
  # Command and process substitutions, outermost first; their own bodies are walked as payloads.
  def substs: if type == "object" then (if .Type == "CmdSubst" or .Type == "ProcSubst" then . else .[] | substs end)
    elif type == "array" then .[] | substs else empty end;
  def enq($item): if .count >= $max then .overflow = true else .count += 1 | .queue += [$item] end;
  def enq_substs($node): reduce ($node | substs) as $s (.; enq({stmts: ($s.Stmts // []), dir: .dir}));
  def resolve($p; $d): if $p == "" or $p == "-" then $d elif $p == "~" then $home elif ($p | startswith("~/")) then $home + $p[1:]
    elif ($p | startswith("/")) then $p else $d + "/" + $p end;
  # Options of a wrapper that take the next word as their value.
  def optval($w; $o): if $w == "nice" then $o == "-n" elif $w == "sudo" then $o | test("^-[ugCDhpRrtTU]$")
    elif $w == "env" then $o | test("^-[uCS]$") elif $w == "timeout" then $o | test("^-[sk]$")
    elif $w == "stdbuf" then $o | test("^-[ioe]$") else false end;
  # The index of the command word: leading assignments and wrappers with their options are skipped.
  def lead($a): ($a | length) as $n
    | {i: 0, done: false}
    | until(.done or .i >= $n;
        if ($a[.i] | test("^[A-Za-z_][A-Za-z0-9_]*=")) then .i += 1
        elif ($a[.i] | test("^(env|command|exec|nohup|time|timeout|stdbuf|builtin|sudo|nice|then|do|else|if|elif|while|until|!|\\{|\\})$") | not) then .done = true
        else $a[.i] as $w | .i += 1
          | until(.i >= $n or ($a[.i] | startswith("-") | not); (if optval($w; $a[.i]) then .i += 1 else . end) | .i += 1)
          | if $w == "timeout" and .i < $n then .i += 1 else . end
        end)
    | .i;
  # A script argument: stdin by name reads stdin; any other script is a file the guard does not read.
  def script($w): if $w == "/dev/stdin" or $w == "/dev/fd/0" then "stdin" else "none" end;
  # A shell runs a `-c` payload (the first word after `-c` that is not an option), a script argument,
  # or stdin.
  def shellin($a; $i): ($a | length) as $n
    | {j: ($i + 1), s: false, r: null}
    | until(.r != null;
        if .j >= $n then .r = "stdin"
        elif ($a[.j] | test("^-[A-Za-z]*c[A-Za-z]*$")) then .j += 1
          | until(.j >= $n or ($a[.j] | test("^[-+]") | not) or .r != null;
              if $a[.j] == "--" or $a[.j] == "-" then .j += 1 | .r = "c"
              elif ($a[.j] | test("^[-+][oO]$|^--(rcfile|init-file)$")) then .j += 2 else .j += 1 end)
          | .r = (if .j < $n then "c" else "none" end)
        elif ($a[.j] | test("^[-+][oO]$|^--(rcfile|init-file)$")) then .j += 2
        elif $a[.j] == "--" then .j += 1 | .r = (if .j < $n and (.s | not) then script($a[.j]) else "stdin" end)
        elif ($a[.j] | test("^[-+]")) then (if ($a[.j] | test("^-[A-Za-z]*s")) then .s = true else . end) | .j += 1
        elif .s | not then .r = script($a[.j])
        else .r = "stdin" end);
  # The literal text `echo` or `printf` writes, with `\n` read as a newline.
  def lit($a; $i; $base): $a[$i + 1:] as $r
    | (if $base == "echo" then first(range(0; $r | length) as $k | select($r[$k] | test("^-[neE]+$") | not) | $k) // ($r | length) else 0 end) as $k
    | $r[$k:] | join(" ") | gsub("\\\\n"; "\n");
  def bits($ws): $ws | map(if .q then "1" else "0" end) | join("");
  # The target of each output redirection (`>`, `>>`, `>|`, `&>`, `&>>`).
  def redirs($rs): .dir as $d
    | .redirs += [($rs // [])[] | select(.Op == ">" or .Op == ">>" or .Op == ">|" or .Op == "&>" or .Op == "&>>")
                  | {dir: $d, t: (.Word | word.t)}];
  # One simple command: its words, its here-string and heredoc text, and what it does to the scan.
  # When an expansion that may be empty sits in a word, a second record follows with those expansions
  # removed (and a word left empty and unquoted dropped, as bash drops it), so `${X}git` reads as git.
  def seg($st; $ws; $nodes):
    ($st.Redirs // []) as $rs
    | ([$rs[] | select(.Op == "<<<") | (.Word | word.t) + "\n"]
       + [$rs[] | select((.Op == "<<" or .Op == "<<-") and .Hdoc != null) | .Hdoc | raw | sub("[^\n]*$"; "")]
       | add // "") as $body
    | enq_substs($nodes) | enq_substs([$rs[] | .Word, .Hdoc]) | redirs($rs)
    | ($ws | map(.t)) as $a
    | lead($a) as $i
    | if $i >= ($a | length) then .last = 0
      else ($a[$i] | sub(".*/"; "")) as $base
      | (.segs | length) as $k
      | .segs += [{dir: .dir, body: $body, quoted: bits($ws[$i:]), words: $a[$i:], pipe: .pipein}]
      | ($ws | map(select((.e // .t) != "" or .q))) as $alt
      | ($alt | map(.e // .t)) as $e
      | (if $e != $a then lead($e) as $ai
           | if $ai < ($e | length) then .segs += [{dir: .dir, body: "", quoted: bits($alt[$ai:]), words: $e[$ai:], pipe: 0}] else . end
         else . end)
      | .pipein = 0 | .last = $k + 1
      | if $base == "cd" then (first(range($i + 1; $a | length) as $j | select($a[$j] | test("^-.") | not) | $j) // null) as $j
          | if $j == null then .dir = resolve("~"; .dir) elif ($a[$j] | test("[$`]|[[:cntrl:]]") | not) then .dir = resolve($a[$j]; .dir) else . end
        elif ($base | test("^(sh|bash|zsh|dash|ksh)$")) then shellin($a; $i) as $r
          | if $r.r == "c" then enq({text: $a[$r.j], dir: .dir})
            elif $r.r == "stdin" then .segs[$k].shin = true
            else . end
        elif $base == "echo" or $base == "printf" then .segs[$k].lit = lit($a; $i; $base)
        elif $base == "cat" then .segs[$k].cat = ([$a[$i + 1:][] | select(startswith("-") | not)] | length == 0)
        elif $base == "eval" and $i < ($a | length) - 1 then enq({text: ($a[$i + 1:] | join(" ")), dir: .dir})
        else . end
      end;
  # Statements in order; `cd` moves the directory for everything after it.
  def stmt($st):
    def stmts($l): reduce ($l // [])[] as $s (.; stmt($s));
    def ifc($c): stmts($c.Cond) | stmts($c.Then) | if $c.Else != null then ifc($c.Else) else . end;
    $st.Cmd as $c
    | ($c.Type // "") as $t
    | if $t == "CallExpr" then seg($st; ($c.Args // []) | map(word); [$c.Assigns, $c.Args])
      elif $t == "DeclClause" then seg($st; [{t: $c.Variant.Value, q: false}] + (($c.Args // []) | map(declword)); $c.Args)
      elif $t == "BinaryCmd" and ($c.Op == "|" or $c.Op == "|&") then stmt($c.X) | .pipein = (if .last > 0 then .last else -1 end) | stmt($c.Y)
      elif $t == "BinaryCmd" and $c.Op == "||" then stmt($c.X) | .pipein = 0 | stmt($c.Y)
      elif $t == "BinaryCmd" then stmt($c.X) | stmt($c.Y)
      elif $t == "TimeClause" or $t == "CoprocClause" then (if $c.Stmt != null then stmt($c.Stmt) else . end) | enq_substs($st.Redirs) | redirs($st.Redirs)
      else (if $t == "Subshell" or $t == "Block" then stmts($c.Stmts)
            elif $t == "IfClause" then ifc($c)
            elif $t == "WhileClause" then stmts($c.Cond) | stmts($c.Do)
            elif $t == "ForClause" then enq_substs($c.Loop) | stmts($c.Do)
            elif $t == "CaseClause" then enq_substs($c.Word) | reduce ($c.Items // [])[] as $it (.; enq_substs($it.Patterns) | stmts($it.Stmts))
            elif $t == "FuncDecl" then stmt($c.Body)
            else enq_substs($c) end)
        | enq_substs($st.Redirs) | redirs($st.Redirs) | .last = 0
      end;
  # After a scan, a shell that reads stdin gets its own heredoc or here-string, or what an `echo`,
  # `printf` or heredoc `cat` pipes into it; what any other producer pipes is not read.
  def stdins($first):
    reduce range($first; .segs | length) as $k (.;
      .segs[$k] as $g
      | if ($g.shin | not) then .
        elif $g.body != "" then enq({text: $g.body, dir: $g.dir})
        else .segs as $all
          | ($g.pipe | until(. <= 0 or ($all[. - 1].cat | not) or $all[. - 1].body != ""; $all[. - 1].pipe)) as $p
          | if $p > 0 and $all[$p - 1].lit != null then enq({text: $all[$p - 1].lit, dir: $g.dir})
            elif $p > 0 and $all[$p - 1].cat then enq({text: $all[$p - 1].body, dir: $g.dir})
            else . end
        end);
  def scan($item): (.segs | length) as $first | .dir = $item.dir | .pipein = 0 | .last = 0
    | reduce $item.stmts[] as $s (.; stmt($s)) | stdins($first);
  {dir: $dir, segs: [], redirs: [], pipein: 0, last: 0, queue: [{stmts: (.Stmts // []), dir: $dir}], next: 0, count: $qn, overflow: false}
  | until(.next >= (.queue | length); .queue[.next] as $it | .next += 1 | if $it.text != null then . else scan($it) end)
  | (.segs[] | [(.dir | enc), (.body | enc), .quoted] + (.words | map(enc)) | join(us)),
    (.redirs[] | us + "redir" + us + (.dir | enc) + us + (.t | enc)),
    (.queue[] | select(.text != null) | us + "payload" + us + (.dir | enc) + us + (.text | enc)),
    (if .overflow then us + "overflow" else empty end),
    us + "qn" + us + (.count | tostring)
