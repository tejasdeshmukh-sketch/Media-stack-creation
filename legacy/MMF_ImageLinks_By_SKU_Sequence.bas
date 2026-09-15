Attribute VB_Name = "MMF_ImageLinks"
' Original Excel macro, kept for reference and for diffing against core.py.
' Designed and Developed by Yash Kende.
Option Explicit

Public Sub MMF_ImageLinks_By_SKU_Sequence()

    Const TOOL_TITLE As String = "Designed and Developed by Yash Kende"

    Dim wb As Workbook
    Dim ws As Worksheet
    Dim tempWs As Worksheet
    Dim outWs As Worksheet

    Set wb = ActiveWorkbook
    Set ws = ActiveSheet

    Dim lastRow As Long
    lastRow = ws.Cells(ws.Rows.Count, "A").End(xlUp).Row

    If lastRow < 2 Then
        MsgBox "No data found.", vbExclamation, TOOL_TITLE
        Exit Sub
    End If

    Application.screenUpdating = False
    Application.enableEvents = False
    Application.Calculation = xlCalculationManual

    On Error Resume Next
    Application.displayAlerts = False
    wb.Worksheets("__MMF_IMAGE_TEMP__").Delete
    wb.Worksheets("output_image_links").Delete
    Application.displayAlerts = True
    On Error GoTo 0

    Set tempWs = wb.Worksheets.Add(After:=wb.Worksheets(wb.Worksheets.Count))
    tempWs.Name = "__MMF_IMAGE_TEMP__"

    tempWs.Range("A1").Value = "SKU"
    tempWs.Range("B1").Value = "Sequence"
    tempWs.Range("C1").Value = "Image Link"

    Dim r As Long
    Dim tempRow As Long
    Dim skuVal As String
    Dim imgVal As String
    Dim seqVal As Variant

    tempRow = 2

    For r = 2 To lastRow
        skuVal = Trim(CStr(ws.Cells(r, "A").Value))
        seqVal = ws.Cells(r, "D").Value
        imgVal = Trim(CStr(ws.Cells(r, "E").Value))

        If skuVal <> "" And imgVal <> "" And IsNumeric(seqVal) Then
            tempWs.Cells(tempRow, "A").Value = skuVal
            tempWs.Cells(tempRow, "B").Value = CDbl(seqVal)
            tempWs.Cells(tempRow, "C").Value = imgVal
            tempRow = tempRow + 1
        End If
    Next r

    If tempRow = 2 Then
        Application.displayAlerts = False
        tempWs.Delete
        Application.displayAlerts = True

        Application.screenUpdating = True
        Application.enableEvents = True
        Application.Calculation = xlCalculationAutomatic

        MsgBox "No valid SKU, Sequence, and Image Link rows found.", vbExclamation, TOOL_TITLE
        Exit Sub
    End If

    tempWs.Range("A1:C" & tempRow - 1).Sort _
        Key1:=tempWs.Range("A2"), Order1:=xlAscending, _
        Key2:=tempWs.Range("B2"), Order2:=xlAscending, _
        Header:=xlYes

    Dim dict As Object
    Set dict = CreateObject("Scripting.Dictionary")

    Dim imgList As Collection
    Dim key As Variant

    For r = 2 To tempRow - 1
        skuVal = CStr(tempWs.Cells(r, "A").Value)
        imgVal = CStr(tempWs.Cells(r, "C").Value)

        If Not dict.Exists(skuVal) Then
            Set imgList = New Collection
            dict.Add skuVal, imgList
        End If

        dict(skuVal).Add imgVal
    Next r

    Dim maxImages As Long
    maxImages = 0

    For Each key In dict.Keys
        If dict(key).Count > maxImages Then
            maxImages = dict(key).Count
        End If
    Next key

    Set outWs = wb.Worksheets.Add(After:=wb.Worksheets(wb.Worksheets.Count))
    outWs.Name = "output_image_links"

    outWs.Cells(1, 1).Value = "Master Id/ Sku"
    outWs.Cells(1, 2).Value = "Main Image"

    Dim c As Long
    For c = 3 To maxImages + 1
        outWs.Cells(1, c).Value = "Other Image " & c - 2
    Next c

    Dim outRow As Long
    Dim i As Long

    outRow = 2

    For Each key In dict.Keys
        outWs.Cells(outRow, 1).Value = key

        For i = 1 To dict(key).Count
            outWs.Cells(outRow, i + 1).Value = dict(key)(i)
        Next i

        outRow = outRow + 1
    Next key

    outWs.Columns.AutoFit

    Application.displayAlerts = False
    tempWs.Delete
    Application.displayAlerts = True

    outWs.Activate

    Application.screenUpdating = True
    Application.enableEvents = True
    Application.Calculation = xlCalculationAutomatic

    MsgBox "Image links output created successfully in the active workbook.", vbInformation, TOOL_TITLE

End Sub
