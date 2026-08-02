@echo off
setlocal

cd /d C:\WEST

if not exist logs mkdir logs

echo [%date% %time%] Verificando sincronizacoes OMIE agendadas... >> logs\omie-sync-task.log
"C:\Users\damas\AppData\Local\Programs\Python\Python313\python.exe" manage.py executar_sincronizacoes_agendadas >> logs\omie-sync-task.log 2>&1
echo [%date% %time%] Verificacao finalizada. >> logs\omie-sync-task.log

endlocal
