"""
Strategy service for creating and managing time-based pricing strategies.
Handles transformation from client requests to ZKong strategy format.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import structlog
import pytz

from app.models.zkong import (
    ZKongStrategyRequest,
    ZKongItemAction,
    ZKongFieldValues,
)
from app.services.supabase_service import SupabaseService
from app.models.database import StoreMapping

logger = structlog.get_logger()


class StrategyService:
    """Service for managing pricing strategies."""

    def __init__(self):
        """Initialize strategy service."""
        self.supabase_service = SupabaseService()

    def _timestamp_to_unix_ms(self, dt: datetime) -> int:
        """
        Convert datetime to Unix timestamp in milliseconds.
        Assumes datetime is in UTC or timezone-aware.

        Args:
            dt: Datetime object (assumed UTC if naive)

        Returns:
            Unix timestamp in milliseconds
        """
        # If datetime is naive (no timezone), assume it's UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        
        return int(dt.timestamp() * 1000)
    
    def _convert_time_to_zkong_timezone(
        self, 
        time_str: str, 
        from_timezone_str: str = "America/Chicago",
        to_timezone_str: Optional[str] = None
    ) -> str:
        """
        Convert time from client's local timezone to ZKong's expected timezone.
        
        Note: Based on ZKong dashboard, merchant timezone is UTC-7.
        ZKong likely expects period_times in the merchant's configured timezone,
        not UTC. So we convert from client timezone (CT) to merchant timezone (UTC-7).
        
        Args:
            time_str: Time in HH:mm:ss format (local time)
            from_timezone_str: Source timezone (default: America/Chicago for CT)
            to_timezone_str: Target timezone (if None, uses merchant timezone UTC-7)
            
        Returns:
            Time string in target timezone (HH:mm:ss format)
        """
        try:
            # Parse time string
            hour, minute, second = map(int, time_str.split(":"))
            
            # Get source timezone
            from_tz = pytz.timezone(from_timezone_str)
            
            # Default target is UTC-7 (ZKong merchant timezone based on dashboard)
            if to_timezone_str is None:
                # Use fixed UTC-7 offset (PST/MST)
                to_tz = pytz.timezone("America/Los_Angeles")  # PST is UTC-8, but we need UTC-7
                # Better: Use fixed offset
                from datetime import timezone, timedelta
                to_tz = timezone(timedelta(hours=-7))
            else:
                to_tz = pytz.timezone(to_timezone_str)
            
            # Create a datetime for today in the source timezone
            today = datetime.now(from_tz).date()
            if isinstance(from_tz, timezone):
                source_dt = datetime.combine(today, datetime.min.time().replace(
                    hour=hour, minute=minute, second=second
                )).replace(tzinfo=from_tz)
            else:
                source_dt = from_tz.localize(datetime.combine(today, datetime.min.time().replace(
                    hour=hour, minute=minute, second=second
                )))
            
            # Convert to target timezone
            if isinstance(to_tz, timezone):
                target_dt = source_dt.astimezone(to_tz)
            else:
                target_dt = source_dt.astimezone(to_tz)
            
            # Return as HH:mm:ss string
            return target_dt.strftime("%H:%M:%S")
        except Exception as e:
            logger.warning(f"Failed to convert time, using original: {e}")
            return time_str  # Fallback to original

    def _build_field_values(
        self,
        price: Optional[str] = None,
        member_price: Optional[str] = None,
        original_price: Optional[str] = None,
        promotion_text: Optional[str] = None,
        unit: Optional[str] = None,
        class_level: Optional[str] = None,
        product_area: Optional[str] = None,
        cust_features: Optional[Dict[str, str]] = None,
    ) -> ZKongFieldValues:
        """
        Build field values for strategy item action.

        Args:
            price: Activity price
            member_price: Activity member price
            original_price: Original price
            promotion_text: Promotional text
            unit: Sales unit
            class_level: Product level
            product_area: Origin
            cust_features: Dictionary of custom features (custFeature1-15)

        Returns:
            ZKongFieldValues object
        """
        field_values_dict = {}

        if price is not None:
            field_values_dict["price"] = str(price)
        if member_price is not None:
            field_values_dict["memberPrice"] = str(member_price)
        if original_price is not None:
            field_values_dict["originalPrice"] = str(original_price)
        if promotion_text is not None:
            field_values_dict["promotionText"] = promotion_text
        if unit is not None:
            field_values_dict["unit"] = unit
        if class_level is not None:
            field_values_dict["classLevel"] = class_level
        if product_area is not None:
            field_values_dict["productArea"] = product_area

        # Add custom features
        if cust_features:
            for i in range(1, 16):
                key = f"custFeature{i}"
                if key in cust_features:
                    field_values_dict[key] = cust_features[key]

        return ZKongFieldValues(**field_values_dict)

    def _get_zkong_item_id(
        self, barcode: str, store_mapping: StoreMapping
    ) -> Optional[int]:
        """
        Get ZKong itemId from barcode via zkong_products table.

        Args:
            barcode: Product barcode
            store_mapping: Store mapping

        Returns:
            ZKong itemId if found, None otherwise
        """
        try:
            # Get product by barcode
            products = (
                self.supabase_service.client.table("products")
                .select("*")
                .eq("barcode", barcode)
                .eq("source_system", store_mapping.source_system)
                .execute()
            )

            if not products.data:
                logger.warning("Product not found by barcode", barcode=barcode)
                return None

            product = products.data[0]
            product_id = product.get("id")

            # Get ZKong product mapping (handle case where table might not exist)
            try:
                zkong_mappings = (
                    self.supabase_service.client.table("zkong_products")
                    .select("*")
                    .eq("product_id", product_id)
                    .eq("store_mapping_id", str(store_mapping.id))
                    .execute()
                )

                if not zkong_mappings.data:
                    logger.warning(
                        "ZKong product mapping not found (table may not exist or product not synced)",
                        product_id=product_id,
                        barcode=barcode,
                    )
                    return None
            except Exception as e:
                # Table might not exist
                logger.warning(
                    "Could not query zkong_products table (may not exist)",
                    error=str(e),
                    barcode=barcode,
                )
                return None

            # Extract itemId from zkong_product_id (may need parsing depending on format)
            zkong_product_id = zkong_mappings.data[0].get("zkong_product_id")
            try:
                return int(zkong_product_id)
            except (ValueError, TypeError):
                logger.warning(
                    "Could not convert zkong_product_id to int",
                    zkong_product_id=zkong_product_id,
                )
                return None

        except Exception as e:
            logger.error("Failed to get ZKong itemId", barcode=barcode, error=str(e))
            return None

    def create_strategy_request(
        self,
        store_mapping: StoreMapping,
        name: str,
        start_date: datetime,
        end_date: datetime,
        trigger_type: int,
        period_type: int,
        period_value: List[int],
        period_times: List[str],
        products: List[Dict[str, Any]],
        template_attr_category: str = "default",
        template_attr: str = "default",
        select_field_name_num: Optional[List[int]] = None,
    ) -> ZKongStrategyRequest:
        """
        Create a ZKong strategy request from client input.

        Args:
            store_mapping: Store mapping configuration
            name: Strategy name
            start_date: Strategy start date
            end_date: Strategy end date
            trigger_type: 1=Fixed period, 2=Always triggered
            period_type: 0=Daily, 1=Weekly, 2=Monthly
            period_value: Period value array
            period_times: Time windows (HH:mm:ss format)
            products: List of product configurations with barcode, prices, etc.
            template_attr_category: Template classification (default: "default")
            template_attr: Template properties (default: "default")
            select_field_name_num: Optional field array (0-19), max 5

        Returns:
            ZKongStrategyRequest object

        Raises:
            ValueError: If product mapping fails or validation fails
        """
        # Convert dates to Unix timestamps (milliseconds)
        # Ensure dates are timezone-aware (assume UTC if naive)
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=pytz.UTC)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=pytz.UTC)
        
        start_timestamp = self._timestamp_to_unix_ms(start_date)
        end_timestamp = self._timestamp_to_unix_ms(end_date)
        
        # Convert period_times from client timezone to UTC
        # ZKong API likely expects UTC times, not merchant timezone
        # Try UTC conversion instead of merchant timezone
        try:
            # First try: Convert to UTC
            utc_period_times = [
                self._convert_time_to_utc(time_str, timezone) for time_str in period_times
            ]
            zkong_period_times = utc_period_times
            
            logger.info(
                "Converted period times to UTC",
                original_times=period_times,
                utc_times=zkong_period_times,
                from_timezone=timezone
            )
        except Exception as e:
            logger.warning(f"Failed UTC conversion, trying merchant timezone: {e}")
            # Fallback: Convert to merchant timezone
            zkong_period_times = [
                self._convert_time_to_zkong_timezone(time_str, timezone) for time_str in period_times
            ]
            logger.info(
                "Converted period times to merchant timezone",
                original_times=period_times,
                zkong_times=zkong_period_times,
                from_timezone=timezone,
                to_timezone="UTC-7"
            )

        # Build item actions
        item_actions = []
        for product_config in products:
            # Allow manual item_id for testing (if table was deleted)
            item_id = product_config.get("item_id")
            
            # If item_id not provided, try to get it from barcode
            if not item_id:
                barcode = product_config.get("barcode")
                if not barcode:
                    raise ValueError(
                        "Product must have either 'barcode' or 'item_id'. "
                        f"Product config: {product_config}"
                    )
                
                # Get ZKong itemId from barcode
                item_id = self._get_zkong_item_id(barcode, store_mapping)
                if not item_id:
                    raise ValueError(
                        f"Could not find ZKong itemId for barcode: {barcode}. "
                        "Product must be synced to ZKong first, or provide 'item_id' manually for testing."
                    )

            # Build field values
            field_values = self._build_field_values(
                price=product_config.get("price"),
                member_price=product_config.get("member_price"),
                original_price=product_config.get("original_price"),
                promotion_text=product_config.get("promotion_text"),
                unit=product_config.get("unit"),
                class_level=product_config.get("class_level"),
                product_area=product_config.get("product_area"),
                cust_features=product_config.get("cust_features"),
            )

            # Create item action
            # Ensure item_id is an integer (Long type in ZKong API)
            item_id_int = int(item_id) if not isinstance(item_id, int) else item_id
            
            # Note: Based on ZKong API docs, itemActions may not support periodTimes
            # periodTimes are defined at strategy level, not per item
            # Try without periodTimes in itemActions first
            item_action = ZKongItemAction(
                itemId=item_id_int,
                fieldValues=field_values,
                # periodTimes removed - should only be at strategy level
            )
            item_actions.append(item_action)

        if not item_actions:
            raise ValueError("No valid products found for strategy")

        # Default select_field_name_num if not provided
        if select_field_name_num is None:
            select_field_name_num = []

        # Validate select_field_name_num (max 5)
        if len(select_field_name_num) > 5:
            raise ValueError("select_field_name_num can have at most 5 items")

        # Create strategy request
        strategy = ZKongStrategyRequest(
            storeId=int(store_mapping.zkong_store_id),
            name=name,
            startDate=start_timestamp,
            endDate=end_timestamp,
            templateAttrCategory=template_attr_category,
            templateAttr=template_attr,
            triggerType=trigger_type,
            periodType=period_type,
            periodValue=period_value,
            periodTimes=zkong_period_times,  # Use ZKong merchant timezone times
            selectFieldNameNum=select_field_name_num,
            itemActions=item_actions,
        )

        return strategy
