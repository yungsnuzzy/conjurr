#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_lotr_matching_scenario():
    """Test the specific Lord of the Rings matching scenario"""
    
    print("=== Testing Lord of the Rings TMDb ID Matching ===")
    
    # Simulate the scenario:
    # - AI recommends "Lord of the Rings" with TMDb ID 120
    # - Plex has "Lord of the Rings - Extended Edition" with TMDb ID 120
    
    # Mock AI recommendation
    ai_recommendation = {
        'title': 'Lord of the Rings',
        'tmdb_id': 120
    }
    
    # Mock Plex library content (what get_library_content_with_guids would return)
    plex_library_tmdb_ids = {
        120: 'Lord of the Rings - Extended Edition',  # Same TMDb ID, different title
        121: 'Lord of the Rings: The Two Towers',
        122: 'Lord of the Rings: The Return of the King'
    }
    
    # Simulate the matching logic from batch_check_availability
    def check_availability(item, available_tmdb_ids):
        title = item.get('title')
        tmdb_id = item.get('tmdb_id')
        
        print(f"Checking: '{title}' (TMDb ID: {tmdb_id})")
        
        # Method 1: TMDb ID matching
        if tmdb_id and tmdb_id in available_tmdb_ids:
            matched_title = available_tmdb_ids[tmdb_id]
            print(f"✅ TMDb ID MATCH: '{title}' matches '{matched_title}' via TMDb ID {tmdb_id}")
            return True
        
        # Method 2: Title matching (fallback)
        print(f"❌ No TMDb ID match found")
        return False
    
    print(f"AI Recommendation: {ai_recommendation}")
    print(f"Plex Library TMDb IDs: {plex_library_tmdb_ids}")
    print()
    
    # Test the matching
    is_available = check_availability(ai_recommendation, plex_library_tmdb_ids)
    
    print(f"\nResult: {'AVAILABLE' if is_available else 'NOT AVAILABLE'}")
    
    # Test additional scenarios
    print("\n=== Additional Test Cases ===")
    
    test_cases = [
        {
            'ai': {'title': 'The Matrix', 'tmdb_id': 603},
            'description': 'Exact title and TMDb ID match'
        },
        {
            'ai': {'title': 'The Matrix', 'tmdb_id': 999},
            'description': 'Same title, wrong TMDb ID (should not match)'
        },
        {
            'ai': {'title': 'Avatar', 'tmdb_id': None},
            'description': 'No TMDb ID available (fallback to title matching)'
        }
    ]
    
    # Add Matrix to mock library
    plex_library_tmdb_ids[603] = 'The Matrix'
    
    for case in test_cases:
        print(f"\n--- {case['description']} ---")
        result = check_availability(case['ai'], plex_library_tmdb_ids)
        print(f"Result: {'AVAILABLE' if result else 'NOT AVAILABLE'}")

if __name__ == "__main__":
    test_lotr_matching_scenario()
