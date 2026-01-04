# Database Migration Guide

This directory contains SQL migration scripts to update your Supabase database from ZKong to Hipoink.

## Migration Steps

### 0. Check Current Database State

**First**, run `000_check_current_state.sql` to see what your current database structure looks like:

1. Open Supabase SQL Editor
2. Copy and paste `000_check_current_state.sql`
3. Run it to see:
   - Which columns exist
   - Which tables exist
   - How much data you have
   - Any foreign key constraints

### 1. Backup Your Database

**IMPORTANT**: Always backup your database before running migrations!

In Supabase:
1. Go to Database → Backups
2. Create a manual backup or ensure automatic backups are enabled

### 2. Run the Migration

1. Open your Supabase project
2. Go to SQL Editor
3. Copy and paste the contents of `001_remove_zkong_add_hipoink.sql`
4. Review the SQL carefully
5. Click "Run" to execute

### 3. Verify the Migration

After running the migration, verify the changes:

```sql
-- Check store_mappings columns
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'store_mappings' 
ORDER BY ordinal_position;

-- Check hipoink_products columns
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'hipoink_products' 
ORDER BY ordinal_position;

-- Check sync_log columns
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'sync_log' 
ORDER BY ordinal_position;
```

### 4. Update Existing Data (if needed)

If you have existing store mappings, you'll need to update them with Hipoink store codes:

```sql
-- Example: Update existing store mappings
-- Replace '001' with your actual Hipoink store codes
UPDATE store_mappings 
SET hipoink_store_code = '001' 
WHERE hipoink_store_code IS NULL;
```

## What the Migration Does

### store_mappings table
- **Removes**: `zkong_merchant_id`, `zkong_store_id`, `esl_system`, `hipoink_store_id`
- **Adds**: `hipoink_store_code` (VARCHAR(255), NOT NULL)

### zkong_products → hipoink_products
- **Renames** table from `zkong_products` to `hipoink_products`
- **Removes**: `zkong_product_id`, `zkong_barcode`
- **Adds**: `hipoink_product_code` (VARCHAR(255), NOT NULL)

### sync_log table
- **Removes**: `zkong_product_id`, `esl_system`
- **Adds**: `hipoink_product_code` (VARCHAR(255), nullable)

### Indexes
- Drops old ZKong indexes
- Creates new Hipoink indexes for better query performance

## Rollback

If you need to rollback the migration, use `002_rollback_zkong.sql`. 

**WARNING**: This will delete Hipoink data and restore the ZKong structure. Only use if absolutely necessary.

## Troubleshooting

### Error: Column does not exist
If you get errors about columns not existing, the migration may have already been partially run. Check which columns exist first:

```sql
SELECT column_name 
FROM information_schema.columns 
WHERE table_name = 'store_mappings';
```

### Error: Cannot drop column (foreign key constraint)
If you get foreign key constraint errors, you may need to drop constraints first:

```sql
-- Find constraints
SELECT constraint_name, constraint_type
FROM information_schema.table_constraints
WHERE table_name = 'store_mappings';

-- Drop specific constraint (replace with actual constraint name)
ALTER TABLE store_mappings DROP CONSTRAINT constraint_name;
```

### Data Migration
If you have existing ZKong product data that needs to be migrated:

```sql
-- This is handled automatically in the migration script
-- But if you need to manually migrate:
UPDATE hipoink_products 
SET hipoink_product_code = zkong_barcode 
WHERE hipoink_product_code IS NULL 
  AND zkong_barcode IS NOT NULL;
```

## After Migration

1. Update your environment variables to use Hipoink credentials
2. Test creating a new store mapping via the API
3. Test syncing a product from Shopify to Hipoink
4. Verify products appear in your Hipoink ESL system

## Support

If you encounter issues:
1. Check the Supabase logs for detailed error messages
2. Verify all foreign key constraints are properly handled
3. Ensure you have the correct permissions to alter tables
4. Review the migration script for any custom constraints in your schema

