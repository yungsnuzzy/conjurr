#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_plex_guid_extraction():
    """Test GUID extraction with various Plex GUID formats"""
    
    print("=== Testing Plex GUID Extraction ===")
    
    # Test the extraction function with various GUID formats
    def _extract_tmdb_id_from_item(item):
        """Extract TMDb ID from a Plex library item's GUID information"""
        try:
            # Check multiple GUID sources
            guids = item.get('Guid', [])
            if not isinstance(guids, list):
                guids = []
            
            # Also check the main 'guid' field (sometimes it's a string)
            main_guid = item.get('guid', '')
            if main_guid:
                guids.append({'id': main_guid})
            
            for guid_obj in guids:
                guid_id = guid_obj.get('id', '') if isinstance(guid_obj, dict) else str(guid_obj)
                
                # Look for TMDb GUID patterns
                if 'tmdb://' in guid_id:
                    # Direct TMDb reference: tmdb://12345
                    try:
                        return int(guid_id.split('tmdb://')[1])
                    except (ValueError, IndexError):
                        continue
                elif 'themoviedb://' in guid_id:
                    # Alternative TMDb format: themoviedb://12345
                    try:
                        return int(guid_id.split('themoviedb://')[1])
                    except (ValueError, IndexError):
                        continue
            
            return None
            
        except Exception as e:
            print(f"Error extracting TMDb ID from item: {e}")
            return None
    
    # Test cases with various GUID formats
    test_cases = [
        {
            'name': 'Direct TMDb GUID',
            'item': {
                'title': 'Lord of the Rings',
                'Guid': [{'id': 'tmdb://120'}]
            },
            'expected': 120
        },
        {
            'name': 'Alternative TMDb format',
            'item': {
                'title': 'The Matrix',
                'Guid': [{'id': 'themoviedb://603'}]
            },
            'expected': 603
        },
        {
            'name': 'Main guid field',
            'item': {
                'title': 'Inception',
                'guid': 'tmdb://27205'
            },
            'expected': 27205
        },
        {
            'name': 'Mixed GUID sources',
            'item': {
                'title': 'Avatar',
                'guid': 'plex://movie/5d776b59ad5437001f79c6f8',
                'Guid': [
                    {'id': 'imdb://tt0499549'},
                    {'id': 'tmdb://19995'}
                ]
            },
            'expected': 19995
        },
        {
            'name': 'No TMDb GUID',
            'item': {
                'title': 'Unknown Movie',
                'Guid': [{'id': 'imdb://tt1234567'}]
            },
            'expected': None
        }
    ]
    
    for case in test_cases:
        print(f"\n--- {case['name']} ---")
        print(f"Title: {case['item']['title']}")
        result = _extract_tmdb_id_from_item(case['item'])
        expected = case['expected']
        
        if result == expected:
            print(f"✅ SUCCESS: Extracted TMDb ID {result}")
        else:
            print(f"❌ FAILED: Expected {expected}, got {result}")

if __name__ == "__main__":
    test_plex_guid_extraction()
