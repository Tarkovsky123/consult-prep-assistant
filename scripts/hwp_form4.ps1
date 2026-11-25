# Fill contest form 4 (proposal) from ops JSON made by draft_to_form4.py, in ONE Hancom process.
# The file-access prompt may appear once: the USER clicks it (never click it automatically).
# ASCII only (PowerShell 5.1 reads BOM-less UTF-8 as cp949); all Korean text comes from the JSON.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\hwp_form4.ps1 -OpsPath 90_output\hwp\ops_form4.json
param([string]$OpsPath)
$ErrorActionPreference = 'Stop'
. 'C:\Users\USER\Desktop\project\manual\scripts\hwp\hwp_common.ps1'
$o = Get-Content -Raw -Encoding UTF8 $OpsPath | ConvertFrom-Json
$hwp = New-Hwp

# Typing shape at the caret. HAction CharShape without a selection also writes zero relative size
# and width ratio (text came out 0.12pt; tested 2026-11-05), so set the CharShape property instead.
function SetChar([double]$pt, [int]$bold) {
  $c = $hwp.CharShape
  foreach ($n in "FaceNameHangul","FaceNameLatin","FaceNameHanja","FaceNameJapanese","FaceNameOther","FaceNameSymbol","FaceNameUser") { [void]$c.SetItem($n, [string]$o.font) }
  foreach ($n in "FontTypeHangul","FontTypeLatin","FontTypeHanja","FontTypeJapanese","FontTypeOther","FontTypeSymbol","FontTypeUser") { [void]$c.SetItem($n, 1) }
  [void]$c.SetItem("Height", [int]$hwp.PointToHwpUnit($pt))
  [void]$c.SetItem("TextColor", [int]$hwp.RGBColor(0,0,0))
  [void]$c.SetItem("Bold", $bold); [void]$c.SetItem("Italic", 0)
  $hwp.CharShape = $c
}
# Shape of the current paragraph. align: 0 justify, 1 left, 2 right, 3 center. left/hang in mm, before/after in pt.
function SetPara([double]$left, [double]$hang, [int]$align, [double]$before, [double]$after, [int]$ls, [int]$keepNext = 0) {
  $pp = $hwp.ParaShape
  [void]$pp.SetItem("KeepWithNext", $keepNext)
  if ($o.nonLatinBreak -ne $null) { [void]$pp.SetItem("BreakNonLatinWord", [int]$o.nonLatinBreak) }  # 0: break Hangul lines at word (eojeol) boundaries, 1: at any character
  [void]$pp.SetItem("LineSpacingType", 0); [void]$pp.SetItem("LineSpacing", $ls)
  [void]$pp.SetItem("AlignType", $align)
  [void]$pp.SetItem("LeftMargin", [int]$hwp.MiliToHwpUnit($left))
  [void]$pp.SetItem("Indentation", [int](-1 * $hwp.MiliToHwpUnit($hang)))
  [void]$pp.SetItem("PrevSpacing", [int]$hwp.PointToHwpUnit($before))
  [void]$pp.SetItem("NextSpacing", [int]$hwp.PointToHwpUnit($after))
  $hwp.ParaShape = $pp
}
function Num($v, [double]$d) { if ($v -eq $null) { return $d } else { return [double]$v } }

$script:fresh = $true   # caret sits in an empty paragraph that the next block may use
function NewPara { if (-not $script:fresh) { [void]$hwp.Run("BreakPara") }; $script:fresh = $false }

function PutPara($b) {
  NewPara
  SetPara (Num $b.left 0) (Num $b.hang 0) ([int](Num $b.align 0)) (Num $b.before 0) (Num $b.after 0) ([int]$o.lineSpacing) ([int](Num $b.keep 0))
  SetChar ([double]$b.pt) ([int](Num $b.bold 0))
  Ins ([string]$b.text)
}

function PutTable($b) {
  NewPara
  SetPara 0 0 0 2 0 100
  SetChar ([double]$b.pt) 0
  [void]$hwp.Run("BreakPara")             # paragraph after the table
  $after = $hwp.GetPosBySet()
  [void]$hwp.Run("MoveUp")                # back to the (empty) table paragraph
  $rows = $b.rows.Count; $cols = $b.cols.Count
  $sum = 0; foreach ($w in $b.cols) { $sum += [double]$w }
  [void]$hwp.HAction.GetDefault("TableCreate", $hwp.HParameterSet.HTableCreation.HSet)
  $t = $hwp.HParameterSet.HTableCreation
  $t.Rows = $rows; $t.Cols = $cols; $t.WidthType = 2; $t.HeightType = 0
  $t.WidthValue = $hwp.MiliToHwpUnit($sum)
  [void]$t.CreateItemArray("ColWidth", $cols)
  $cw = $t.ColWidth
  for ($i = 0; $i -lt $cols; $i++) {
    # the HWP array exposes a settable parameterized property Item(int), not SetItem
    [void]$cw.GetType().InvokeMember("Item", [Reflection.BindingFlags]::SetProperty, $null, $cw, @([int]$i, [int]$hwp.MiliToHwpUnit([double]$b.cols[$i])))
  }
  try { $t.TableProperties.TreatAsChar = 1 } catch { L ("  treat-as-char (table) failed: " + $_) }
  [void]$hwp.HAction.Execute("TableCreate", $t.HSet)
  for ($r = 0; $r -lt $rows; $r++) {
    for ($c = 0; $c -lt $cols; $c++) {
      $bold = 0; if ($r -eq 0) { $bold = 1 }
      SetPara 0 0 1 0 0 130
      SetChar ([double]$b.pt) $bold
      Ins ([string]$b.rows[$r][$c])
      if (-not ($r -eq $rows - 1 -and $c -eq $cols - 1)) { [void]$hwp.Run("TableRightCell") }
    }
  }
  [void]$hwp.Run("Cancel")
  [void]$hwp.SetPosBySet($after)
  $script:fresh = $true
  L ("  table " + $rows + "x" + $cols)
}

function PutFigure($b) {
  NewPara
  SetPara 0 0 3 4 2 100 1   # keep the figure with its caption (the next paragraph)
  $ctrl = $hwp.InsertPicture([string]$b.path, $true, 1, $false, $false, 0, [double]$b.widthMM, [double]$b.heightMM)
  if ($ctrl -eq $null) { L "  figure insert FAILED" } else {
    try { $prop = $ctrl.Properties; [void]$prop.SetItem("TreatAsChar", $true); $ctrl.Properties = $prop } catch { L ("  treat-as-char failed: " + $_) }
  }
  [void]$hwp.Run("Cancel"); [void]$hwp.Run("MoveParaEnd")
  L ("  figure " + $b.widthMM + "x" + $b.heightMM + " mm")
}

# Write lines into the cell to the right of the label cell that holds $anchor.
function FillRight([string]$anchor, $lines, [double]$pt, [string]$name) {
  if (-not (Find1 $anchor)) { L ("NOT FOUND: " + $name); return }
  [void]$hwp.Run("Cancel"); [void]$hwp.Run("TableRightCell")
  ClearCell
  $first = $true
  foreach ($ln in $lines) {
    if (-not $first) { [void]$hwp.Run("BreakPara") }
    SetPara 0 3.6 0 0 1 ([int]$o.lineSpacing)
    SetChar $pt 0
    Ins ([string]$ln); $first = $false
  }
  L ("  " + $name + ": " + $lines.Count + " lines")
}

try {
if (-not $hwp.Open([string]$o.template, "HWP", "forceopen:true")) { L "Open failed"; exit 1 }
L ("pages in template: " + $hwp.PageCount)

# 1) Drop forms 1-3: delete from the document start to the end of the paragraph just before form 4.
[void]$hwp.Run("MoveDocEnd")
if (Find ([string]$o.cutAfter) "Backward") {
  [void]$hwp.Run("Cancel"); [void]$hwp.Run("MoveParaEnd"); [void]$hwp.Run("MoveSelDocBegin"); [void]$hwp.Run("Delete")
  [void]$hwp.Run("Delete")
  L ("cut forms 1-3, pages now: " + $hwp.PageCount)
} else { L "NOT FOUND: cut anchor" }

# 1b) Paper size and margins (ops.page, mm). Keeps the form's text area so its fixed-width tables still fit.
if ($o.page) {
  $sd = $hwp.HParameterSet.HSecDef
  [void]$hwp.HAction.GetDefault("PageSetup", $sd.HSet)
  $sd.PageDef.PaperWidth = $hwp.MiliToHwpUnit([double]$o.page.w); $sd.PageDef.PaperHeight = $hwp.MiliToHwpUnit([double]$o.page.h)
  $sd.PageDef.LeftMargin = $hwp.MiliToHwpUnit([double]$o.page.left); $sd.PageDef.RightMargin = $hwp.MiliToHwpUnit([double]$o.page.right)
  $sd.PageDef.TopMargin = $hwp.MiliToHwpUnit([double]$o.page.top); $sd.PageDef.BottomMargin = $hwp.MiliToHwpUnit([double]$o.page.bottom)
  $sd.PageDef.HeaderLen = $hwp.MiliToHwpUnit([double]$o.page.header); $sd.PageDef.FooterLen = $hwp.MiliToHwpUnit([double]$o.page.footer)
  [void]$sd.HSet.SetItem("ApplyClass", 24); [void]$sd.HSet.SetItem("ApplyTo", 3)
  [void]$hwp.HAction.Execute("PageSetup", $sd.HSet)
  L ("page set: " + $o.page.w + "x" + $o.page.h + " mm, pages now: " + $hwp.PageCount)
}

# 2) Title cell, idea summary, summary table (bottom row first so labels never hit inserted text).
if (Find1 ([string]$o.title.anchor)) {
  ClearCell
  SetPara 0 0 3 0 0 130
  SetChar ([double]$o.title.pt) 1
  Ins ([string]$o.title.text)
  L "  title"
} else { L "NOT FOUND: title" }
FillRight ([string]$o.summary.anchor) $o.summary.lines ([double]$o.summary.pt) "summary"
foreach ($r in $o.rows) { FillRight ([string]$r.anchor) $r.lines ([double]$o.rowPt) ([string]$r.anchor) }

# 3) Sections 7..1: replace the guide line with the blocks.
foreach ($s in $o.sections) {
  if (-not (Find1 ([string]$s.guide))) { L ("NOT FOUND: guide " + $s.no); continue }
  [void]$hwp.Run("Cancel"); [void]$hwp.Run("MoveParaBegin"); [void]$hwp.Run("MoveSelParaEnd"); [void]$hwp.Run("Delete")
  $script:fresh = $true
  L ("section " + $s.no + ": " + $s.blocks.Count + " blocks")
  foreach ($b in $s.blocks) {
    if ($b.t -eq "p") { PutPara $b } elseif ($b.t -eq "table") { PutTable $b } elseif ($b.t -eq "fig") { PutFigure $b }
  }
  # the form leaves two empty paragraphs after each guide line: keep one as the gap before the next heading
  [void]$hwp.Run("MoveParaEnd"); [void]$hwp.Run("Delete")
  if ($script:fresh) { [void]$hwp.Run("Delete") }
}

# 3b) Keep each form section heading on the same page as its first paragraph (no heading alone at a page foot)
foreach ($hd in $o.headings) {
  if (Find1 ([string]$hd)) {
    [void]$hwp.Run("Cancel")
    $hp = $hwp.ParaShape; [void]$hp.SetItem("KeepWithNext", 1); $hwp.ParaShape = $hp
  } else { L ("NOT FOUND: heading " + $hd) }
}

# 4) Document properties (the template carries its maker's name as author)
if ($o.docinfo) {
  $si = $hwp.HParameterSet.HSummaryInfo
  [void]$hwp.HAction.GetDefault("DocSummaryInfo", $si.HSet)
  $si.Title = [string]$o.docinfo.title; $si.Author = [string]$o.docinfo.author
  [void]$hwp.HAction.Execute("DocSummaryInfo", $si.HSet)
  L "doc info set"
}

$n = $hwp.PageCount
L ("pages: " + $n)
if ($o.maxPages -and $n -gt [int]$o.maxPages) { L ("OVER LIMIT: " + $n + " pages > " + $o.maxPages) }
[void]$hwp.SaveAs([string]$o.outHwp, "HWP", "")
[void]$hwp.SaveAs([string]$o.outPdf, "PDF", "")
L ("saved: " + $o.outHwp)
} catch {
  L ("ERROR: " + $_.Exception.Message + " @ line " + $_.InvocationInfo.ScriptLineNumber)
} finally {
  # never save over the template: discard the in-memory document and close this Hancom instance
  try { [void]$hwp.Clear(1) } catch {}
  try { [void]$hwp.Quit() } catch {}
}
L "done"
