-- Read-only inventory of all columns and actual values for a single TIRBazar card.
-- Run in SSMS against the internal SQL Server. Does not modify any data.
USE TIRBazar;
SET NOCOUNT ON;
DECLARE @OID int = 20061;

-- 1. Complete column inventory, including data types.
SELECT s.name AS schema_name, t.name AS table_name,
       c.column_id, c.name AS column_name,
       ty.name AS sql_type, c.max_length, c.is_nullable
FROM sys.tables AS t
JOIN sys.schemas AS s ON s.schema_id=t.schema_id
JOIN sys.columns AS c ON c.object_id=t.object_id
JOIN sys.types AS ty ON ty.user_type_id=c.user_type_id
WHERE s.name='dbo' AND t.name IN
 ('Vozidlo','Prodej','VykupVozidla','VykoupeniZKomise')
ORDER BY t.name,c.column_id;

-- 2. Entire vehicle row as JSON, without manually selecting columns.
SELECT v.* FROM dbo.Vozidlo AS v WHERE v.OID=@OID FOR JSON PATH, INCLUDE_NULL_VALUES;

-- 3. Related purchase/sale history, preserving all fields.
SELECT p.* FROM dbo.Prodej AS p WHERE p.Vozidlo=@OID FOR JSON PATH, INCLUDE_NULL_VALUES;
SELECT x.* FROM dbo.VykupVozidla AS x WHERE x.Vozidlo=@OID FOR JSON PATH, INCLUDE_NULL_VALUES;
SELECT x.* FROM dbo.VykoupeniZKomise AS x WHERE x.Vozidlo=@OID FOR JSON PATH, INCLUDE_NULL_VALUES;

-- 4. Other foreign keys referencing dbo.Vozidlo (possible related data).
SELECT SCHEMA_NAME(parent.schema_id) AS referencing_schema,
       parent.name AS referencing_table,
       pc.name AS referencing_column,
       fk.name AS foreign_key
FROM sys.foreign_key_columns AS fkc
JOIN sys.foreign_keys AS fk ON fk.object_id=fkc.constraint_object_id
JOIN sys.tables AS parent ON parent.object_id=fkc.parent_object_id
JOIN sys.columns AS pc ON pc.object_id=fkc.parent_object_id AND pc.column_id=fkc.parent_column_id
WHERE fkc.referenced_object_id=OBJECT_ID('dbo.Vozidlo')
ORDER BY referencing_schema,referencing_table,referencing_column;
