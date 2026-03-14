from dataclasses import dataclass


@dataclass
class Track:
    track_id: int
    bbox: list


class TrackerAdapter:
    def __init__(self, tracker):
        self.tracker = tracker

    def update(self, detections, frame=None):
        raw_tracks = self.tracker.update(detections, frame)

        tracks = []
        for t in raw_tracks:
            tracks.append(
                Track(
                    track_id=int(t["track_id"]),
                    bbox=t["bbox"],
                )
            )

        return tracks
