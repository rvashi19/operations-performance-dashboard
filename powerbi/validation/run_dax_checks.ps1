# Runs reconciliation DAX queries against the model open in Power BI Desktop (local Analysis Services engine)
# and prints JSON. Usage (Power BI Desktop must have Ops311Dashboard.pbip open and refreshed):
#   powershell -ExecutionPolicy Bypass -File powerbi/validation/run_dax_checks.ps1 > powerbi/validation/dax_results.json
$ErrorActionPreference = "Stop"
$pkg = (Get-AppxPackage Microsoft.MicrosoftPowerBIDesktop).InstallLocation
if (-not $pkg) { $pkg = "C:\Program Files\Microsoft Power BI Desktop" }
[void][Reflection.Assembly]::LoadFrom((Join-Path $pkg "bin\Microsoft.PowerBI.AdomdClient.dll"))
$portFile = Get-ChildItem "$env:USERPROFILE\Microsoft\Power BI Desktop Store App\AnalysisServicesWorkspaces\*\Data\msmdsrv.port.txt",
    "$env:LOCALAPPDATA\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces\*\Data\msmdsrv.port.txt" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$port = [Text.Encoding]::Unicode.GetString([IO.File]::ReadAllBytes($portFile.FullName)).Trim()
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port")
$conn.Open()

$queries = [ordered]@{
  headline = @"
EVALUATE ROW(
 "total", [Total Requests], "closed", [Closed Requests], "open", [Open Requests], "unknown", [Unknown Status Requests],
 "resolution_rate", [Resolution Rate], "avg_h", [Avg Resolution Hours], "median_h", [Median Resolution Hours],
 "p90_h", [P90 Resolution Hours], "within_target", [Within 7-Day Analytical Target %],
 "current_backlog", [Current Backlog], "overdue", [Overdue Open Requests],
 "record_pass", [Record-Level DQ Pass Rate], "request_pass", [Request-Level DQ Pass Rate], "dq_issues", [DQ Issues],
 "manual_review", [Pending Manual Review])
"@
  backlog_dec_2025 = "EVALUATE CALCULATETABLE(ROW(""backlog"", [Backlog At Period End]), Calendar[year_month] = ""2025-12"")"
  backlog_jun_2025 = "EVALUATE CALCULATETABLE(ROW(""backlog"", [Backlog At Period End]), Calendar[year_month] = ""2025-06"")"
  rolling_by_month = "EVALUATE SUMMARIZECOLUMNS(Calendar[year_month], ""created"", [Requests Created], ""closed"", [Requests Closed], ""rolling3"", [Requests Created 3M Rolling Avg])"
  slicer_agency_dob = "EVALUATE CALCULATETABLE(ROW(""requests"", [Total Requests], ""current_backlog"", [Current Backlog], ""dq_issues"", [DQ Issues], ""median_h"", [Median Resolution Hours]), Agency[agency_code] = ""DOB"")"
  slicer_complaint = "EVALUATE CALCULATETABLE(ROW(""requests"", [Total Requests], ""current_backlog"", [Current Backlog], ""dq_issues"", [DQ Issues]), Requests[complaint_type] = ""Root/Sewer/Sidewalk Condition"")"
  slicer_zip = "EVALUATE CALCULATETABLE(ROW(""requests"", [Total Requests], ""current_backlog"", [Current Backlog]), Requests[incident_zip] = ""10312"")"
  slicer_status = "EVALUATE CALCULATETABLE(ROW(""requests"", [Total Requests], ""current_backlog"", [Current Backlog]), Requests[status] = ""In Progress"")"
  dq_by_rule = "EVALUATE SUMMARIZECOLUMNS(DQIssues[rule_id], ""issues"", [DQ Issues])"
  agency_dq_pct = "EVALUATE TOPN(3, SUMMARIZECOLUMNS(Agency[agency_code], ""pct"", [Published Requests With Issues %]), [pct], DESC)"
}
$out = [ordered]@{}
foreach ($k in $queries.Keys) {
  $cmd = $conn.CreateCommand(); $cmd.CommandText = $queries[$k]
  $r = $cmd.ExecuteReader(); $rows = @()
  while ($r.Read()) { $row = [ordered]@{}; for ($i = 0; $i -lt $r.FieldCount; $i++) { $row[$r.GetName($i)] = $r.GetValue($i) }; $rows += $row }
  $r.Close(); $out[$k] = $rows
}
$conn.Close()
$out | ConvertTo-Json -Depth 5

