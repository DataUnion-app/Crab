from dao.users_dao import user_dao
from dao.metadata_dao import image_metadata_dao
from dao.rewards_dao import rewards_dao
from commands.base_command import BaseCommand
from collections import defaultdict
import logging
from commands.dataunions.brainstem.participant_projection import (
    BrainstemFilterSpec,
    participant_selector,
    project_participants,
)

class BrainstemRecordingStatisticsCommand(BaseCommand):

    def __init__(self):
        super().__init__()
        self.image_metadata_dao = image_metadata_dao

    def execute(self):
        self.successful = True

        try:
            result = image_metadata_dao.query_view('brainstem', 'recording-statistics', group=True)
            aggregated = {
                'total_count': 0,
                'total_length': 0,
                'last_24h_count': 0,
                'type_counts': defaultdict(int),
                'user_counts': defaultdict(int)
            }

            for row in result.get('rows', []):
                value = row['value']
                aggregated['total_count'] += value.get('total_count', 0)
                aggregated['total_length'] += value.get('total_length', 0)
                aggregated['last_24h_count'] += value.get('last_24h_count', 0)

                for k, v in value.get('type_counts', {}).items():
                    aggregated['type_counts'][k] += v
                for k, v in value.get('user_counts', {}).items():
                    aggregated['user_counts'][k] += v

            # Optional: convert defaultdicts to dicts
            aggregated['type_counts'] = dict(aggregated['type_counts'])
            aggregated['user_counts'] = dict(aggregated['user_counts'])

        except Exception as e:
            print(f"Error querying view: {e}")
            logging.exception(e)
            aggregated = {
                'total_count': 0,
                'total_length': 0,
                'last_24h_count': 0,
                'type_counts': {},
                'user_counts': {}
            }
        try:
            total_rewards = rewards_dao.query_view('brainstem', 'claims')['rows'][0]['value']
        except:
            total_rewards = 0

        return {
            'total_count': aggregated['total_count'],
            'total_length': aggregated['total_length'],
            'type_counts': aggregated['type_counts'],
            'last_24h_count': aggregated['last_24h_count'],
            'users': len(aggregated['user_counts']),
            'total_rewards': total_rewards
        }

class BrainstemRecordingFilterCommand(BaseCommand):
    def __init__(self, recording_type: str, min_age: int = None, max_age: int = None, gender: str = None,
                 ethnicity: str = None, min_amount: int = 0, max_amount: int = 9999999, page: int = 0,
                 per_page: int = 50, sort_by: str = "total_amount", sort_direction: str = "descending"):
        super().__init__()
        self.spec = BrainstemFilterSpec(
            recording_type=recording_type or "",
            min_age=min_age if min_age is not None else 0,
            max_age=max_age if max_age is not None else 120,
            gender=gender or "",
            ethnicity=ethnicity or "",
            min_amount=min_amount if min_amount is not None else 0,
            max_amount=max_amount if max_amount is not None else 9_999_999,
            page=page,
            per_page=per_page,
            sort_by=sort_by or "total_amount",
            sort_direction=sort_direction or "descending",
        )
        self.user_dao = user_dao

    def execute(self):
        self.successful = True
        candidates = self.user_dao.iter_query({
            "selector": participant_selector(self.spec),
            "fields": [
                "_id", "recording_data", "metadata", "usage_flag",
                "guidelines_acceptance_flag"
            ],
        }, batch_size=max(100, self.spec.per_page))
        return project_participants(candidates, self.spec)
