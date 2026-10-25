-- DENNÍ POV / TIRBazar: complete read-only inspection of one vehicle
-- TARGET OID = 20061 (VIN ZCFC135D8J5188058).
-- Run in SQL Server Management Studio connected to VCSERVER.
-- SELECT only: makes no changes to TIRBazar.
USE TIRBazar;
SET NOCOUNT ON;
DECLARE @OID INT = 20061;

-- Verify target. Do not dump another vehicle if the OID/VIN pairing changed.
IF NOT EXISTS (SELECT 1 FROM dbo.Vozidlo WHERE OID=@OID AND VIN='ZCFC135D8J5188058')
BEGIN
    SELECT 'TARGET_NOT_FOUND_OR_MISMATCH' AS diagnostic;
    RETURN;
END;

-- 1: Every column in dbo.Vozidlo with its SQL type.
SELECT c.column_id, c.name AS column_name, ty.name AS sql_type,
       c.max_length, c.precision, c.scale, c.is_nullable
FROM sys.columns c
JOIN sys.types ty ON ty.user_type_id=c.user_type_id
WHERE c.object_id=OBJECT_ID('dbo.Vozidlo')
ORDER BY c.column_id;

-- 2: Every value of the target row, including NULLs.
SELECT v.* FROM dbo.Vozidlo AS v WHERE v.OID=@OID
FOR JSON PATH, INCLUDE_NULL_VALUES;

-- 3: List all declared foreign-key relationships to dbo.Vozidlo.
SELECT SCHEMA_NAME(t.schema_id) AS schema_name, t.name AS table_name,
       c.name AS referencing_column, fk.name AS foreign_key
FROM sys.foreign_key_columns fkc
JOIN sys.foreign_keys fk ON fk.object_id=fkc.constraint_object_id
JOIN sys.tables t ON t.object_id=fkc.parent_object_id
JOIN sys.columns c ON c.object_id=fkc.parent_object_id AND c.column_id=fkc.parent_column_id
WHERE fkc.referenced_object_id=OBJECT_ID('dbo.Vozidlo')
  AND fkc.referenced_column_id=COLUMNPROPERTY(OBJECT_ID('dbo.Vozidlo'),'OID','ColumnId')
ORDER BY schema_name,table_name,referencing_column;

-- 4: Inspect all direct referencing records where FK points to Vozidlo.OID.
-- Per-table cap prevents huge output while giving an existence/sample view.
-- Results are JSON by table, including NULL fields.
DECLARE @schema SYSNAME, @table SYSNAME, @column SYSNAME, @statement NVARCHAR(MAX);
DECLARE related CURSOR LOCAL FAST_FORWARD FOR
    SELECT SCHEMA_NAME(t.schema_id), t.name, c.name
    FROM sys.foreign_key_columns fkc
    JOIN sys.tables t ON t.object_id=fkc.parent_object_id
    JOIN sys.columns c ON c.object_id=fkc.parent_object_id AND c.column_id=fkc.parent_column_id
    WHERE fkc.referenced_object_id=OBJECT_ID('dbo.Vozidlo')
      AND fkc.referenced_column_id=COLUMNPROPERTY(OBJECT_ID('dbo.Vozidlo'),'OID','ColumnId')
    ORDER BY 1,2,3;
OPEN related;
FETCH NEXT FROM related INTO @schema,@table,@column;
WHILE @@FETCH_STATUS=0
BEGIN
    SELECT @schema AS schema_name,@table AS table_name,@column AS referencing_column;
    SET @statement=N'SELECT TOP (100) * FROM '
        +QUOTENAME(@schema)+N'.'+QUOTENAME(@table)
        +N' WHERE '+QUOTENAME(@column)+N'=@target FOR JSON PATH, INCLUDE_NULL_VALUES;';
    EXEC sp_executesql @statement,N'@target INT',@target=@OID;
    FETCH NEXT FROM related INTO @schema,@table,@column;
END;
CLOSE related;
DEALLOCATE related;

-- 5: Known links: also read these even when they have no declared FK.
SELECT p.* FROM dbo.Prodej p WHERE p.Vozidlo=@OID FOR JSON PATH,INCLUDE_NULL_VALUES;
SELECT v.* FROM dbo.VykupVozidla v WHERE v.Vozidlo=@OID FOR JSON PATH,INCLUDE_NULL_VALUES;
SELECT k.* FROM dbo.VykoupeniZKomise k WHERE k.Vozidlo=@OID FOR JSON PATH,INCLUDE_NULL_VALUES;
