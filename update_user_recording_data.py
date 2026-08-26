#!/usr/bin/env python3
"""
Standalone script to aggregate metadata records by user and update user documents with recording_data.

This script:
1. Gets all users from the user database
2. For each user, queries their metadata records (created_by = user's public_address)
3. Aggregates data by record_type for each user
4. Updates user documents with the aggregated recording_data

Usage:
    python update_user_recording_data.py
"""

import sys
import os
import logging

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dao.users_dao import user_dao
from dao.metadata_dao import image_metadata_dao
from collections import defaultdict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


def aggregate_and_update_recording_data():
    """
    Aggregate metadata records by user and update user documents with recording_data.
    First gets all users, then for each user queries their metadata records.
    """
    try:
        # First, get all users
        logging.info("Querying all users...")
        users_query = {
            "selector": {
                "_id": {"$gt": None},
                "public_address": {"$exists": True}
            },
            "fields": ["_id", "public_address"]
        }
        users = user_dao.query_all(users_query)
        logging.info(f"Found {len(users)} users")
        
        updated_count = 0
        skipped_count = 0
        
        # Process each user
        for user in users:
            public_address = user.get("public_address")
            if not public_address:
                skipped_count += 1
                continue
            
            try:
                # Query metadata records for this user
                metadata_query = {
                    "selector": {
                        "created_by": public_address,
                        "record_type": {"$exists": True}
                    },
                    "fields": ["record_type", "duration", "rows"]
                }
                
                metadata_records = image_metadata_dao.query_all(metadata_query)
                
                # Initialize aggregates for this user
                aggregates = {
                    "total_amount": 0,
                    "total_rows": 0,
                    "total_durations": 0,
                    "counts": defaultdict(int),
                    "durations": defaultdict(int),
                    "rows": defaultdict(int)
                }
                
                # Aggregate data from metadata records
                for record in metadata_records:
                    record_type = record.get("record_type")
                    duration = record.get("duration", 0)
                    rows = record.get("rows", 0)
                    
                    if not record_type:
                        continue
                    
                    # Update aggregates
                    aggregates["total_amount"] += 1
                    aggregates["total_rows"] += rows
                    aggregates["total_durations"] += duration
                    aggregates["counts"][record_type] += 1
                    aggregates["durations"][record_type] += duration
                    aggregates["rows"][record_type] += rows
                
                # Get full user document
                user_doc = user_dao.get_doc_by_id(user["_id"])
                
                # Prepare recording_data
                recording_data = {
                    "total_amount": aggregates["total_amount"],
                    "total_rows": aggregates["total_rows"],
                    "total_durations": aggregates["total_durations"],
                    "counts": dict(aggregates["counts"]),
                    "durations": dict(aggregates["durations"]),
                    "rows": dict(aggregates["rows"])
                }
                
                # Update user document
                user_doc["recording_data"] = recording_data
                user_dao.update_doc(user_doc["_id"], user_doc)
                updated_count += 1
                
                if updated_count % 10 == 0:
                    logging.info(f"Updated {updated_count} users so far...")
                
            except Exception as e:
                logging.error(f"Error processing user {public_address}: {e}")
                skipped_count += 1
                continue
        
        logging.info("=" * 50)
        logging.info("Update completed!")
        logging.info(f"Total users processed: {len(users)}")
        logging.info(f"Successfully updated: {updated_count}")
        logging.info(f"Skipped/Failed: {skipped_count}")
        logging.info("=" * 50)
        
        return {
            "success": True,
            "updated_users": updated_count,
            "skipped_users": skipped_count,
            "total_users_processed": len(users)
        }
        
    except Exception as e:
        logging.exception(f"Error in aggregate_and_update_recording_data: {e}")
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    result = aggregate_and_update_recording_data()
    if result.get("success"):
        print(f"\n✓ Successfully updated {result['updated_users']} users")
        if result['skipped_users'] > 0:
            print(f"⚠ Skipped {result['skipped_users']} users")
        sys.exit(0)
    else:
        print(f"\n✗ Error: {result.get('error', 'Unknown error')}")
        sys.exit(1)
