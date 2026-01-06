# Time-Based Pricing System

## What Is It?

The time-based pricing system lets you schedule automatic price changes for your products. You can set products to go on sale at specific times and automatically return to their original prices when the sale period ends.

Think of it like a digital store manager that changes prices on a schedule - no manual work needed!

## How It Works

### The Basics

1. **You create a schedule** with:
   - Which products to change
   - What the sale price should be
   - When the sale should start and end
   - Whether it should repeat (daily, weekly, etc.)

2. **The system automatically**:
   - Applies the sale price at the scheduled start time
   - Restores the original price at the scheduled end time
   - Repeats this cycle if you set it to repeat

### Example: Daily Sale

Let's say you want a product to go on sale every day from 9:50 PM to 10:00 PM:

- **9:50 PM**: System automatically changes price to sale price ($10.99)
- **10:00 PM**: System automatically changes price back to original ($5.99)
- **Next day at 9:50 PM**: Repeats automatically

You set it up once, and it runs automatically every day!

## Creating a Schedule

When you create a time-based pricing schedule, you provide:

### Required Information

- **Schedule Name**: A name to identify this schedule (e.g., "Evening Flash Sale")
- **Products**: Which products to include in the sale
  - Product barcode
  - Sale price
  - Original price (to restore later)
- **Time Slots**: When the sale should run
  - Start time (e.g., 9:50 PM)
  - End time (e.g., 10:00 PM)
- **Start Date**: When the schedule should begin
- **Repeat Type**: How often it should repeat
  - **None**: Runs once and stops
  - **Daily**: Repeats every day
  - **Weekly**: Repeats on specific days of the week
  - **Monthly**: Repeats on the same day each month

### Optional Information

- **End Date**: When the schedule should stop (for repeating schedules)
- **Trigger Stores**: Specific store locations to apply the sale to
- **Trigger Days**: For weekly schedules, which days of the week (Monday, Tuesday, etc.)

## What Happens Behind the Scenes

### When You Create a Schedule

1. The system saves your schedule
2. It calculates when the first price change should happen
3. It sets up automatic triggers for future price changes

### The Automatic Process

Every minute, the system checks if any schedules need to run:

1. **At the start time**:
   - Finds the product in your system
   - Changes only the price (keeps everything else the same - name, image, description, etc.)
   - Updates the price on your electronic shelf labels
   - Sets a reminder to restore the price at the end time

2. **At the end time**:
   - Finds the product again
   - Changes the price back to the original price
   - Updates the price on your electronic shelf labels
   - If it's a repeating schedule, sets up the next occurrence

## Important Features

### Preserves Product Information

When prices change, **only the price changes**. Everything else stays exactly the same:
- Product name
- Product image
- Product description
- SKU/barcode
- All other product details

This ensures your products display correctly with just the price updated.

### Timezone Handling

The system uses your store's local timezone, so:
- If you set a sale for 9:50 PM, it happens at 9:50 PM in your store's time zone
- You don't need to worry about converting times
- The system handles all timezone conversions automatically

### Multiple Stores

You can target specific stores with the same schedule:
- Apply a sale to Store A and Store B, but not Store C
- Each store runs on its own local time
- Perfect for regional promotions

## Repeat Types Explained

### None (One-Time Sale)

- Runs once on the start date
- Applies sale price at start time
- Restores original price at end time
- Then stops

**Best for**: Limited-time promotions, flash sales, special events

### Daily

- Repeats every single day
- Same times every day
- Continues indefinitely (unless you set an end date)

**Best for**: Happy hour pricing, daily specials, routine promotions

### Weekly

- Repeats on specific days of the week
- You choose which days (e.g., Monday, Wednesday, Friday)
- Same times on those days
- Continues weekly

**Best for**: Weekday specials, weekend sales, recurring weekly promotions

### Monthly

- Repeats on the same day each month
- Same times
- Continues monthly

**Best for**: Monthly sales, anniversary promotions, recurring monthly events

## Example Scenarios

### Scenario 1: Happy Hour Pricing

**Goal**: Reduce prices every day from 4:00 PM to 6:00 PM

**Setup**:
- Time slot: 4:00 PM - 6:00 PM
- Repeat: Daily
- Products: Selected beverages

**Result**: Every day at 4:00 PM, prices automatically drop. At 6:00 PM, they automatically return to normal.

### Scenario 2: Weekend Sale

**Goal**: Weekend-only pricing on specific products

**Setup**:
- Time slots: 9:00 AM - 9:00 PM
- Repeat: Weekly
- Trigger days: Saturday, Sunday
- Products: Selected items

**Result**: Every Saturday and Sunday, prices change at 9:00 AM and return to normal at 9:00 PM.

### Scenario 3: Flash Sale

**Goal**: One-time 30-minute flash sale

**Setup**:
- Time slot: 2:00 PM - 2:30 PM
- Repeat: None
- Start date: Today
- Products: Featured items

**Result**: Today at 2:00 PM, prices drop. At 2:30 PM, they return to normal. Then it stops.

## What You Need to Know

### Before Creating a Schedule

- Make sure products exist in your system
- Know the original prices (the system can look them up)
- Decide on sale prices
- Choose your time slots carefully
- Consider your store's timezone

### After Creating a Schedule

- The schedule is active immediately
- It will run automatically at the scheduled times
- You can see when it last ran and when it will run next
- You can deactivate it anytime if needed

### Best Practices

1. **Test first**: Create a short test schedule to verify it works
2. **Check times**: Make sure your time slots make sense (end time after start time)
3. **Original prices**: Verify the original prices are correct
4. **Store selection**: Double-check which stores are included
5. **Monitor**: Check that prices change as expected the first few times

## Troubleshooting

### Price Didn't Change

- Check if the schedule is active
- Verify the current time is within the time slot
- Check if the product exists in the system
- Verify the store code is correct

### Price Changed at Wrong Time

- Check your store's timezone setting
- Verify the time slot times are correct
- Make sure the schedule's start date is correct

### Price Didn't Restore

- Check if the schedule is still active
- Verify the end time is correct
- Check if there was an error in the logs

## Summary

The time-based pricing system is like having an automatic store manager that:
- Changes prices on schedule
- Restores prices automatically
- Repeats on your schedule
- Works across multiple stores
- Handles timezones automatically
- Preserves all product information

Set it up once, and it runs automatically - no manual work required!
