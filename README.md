# Roborock Obstacle Photos

Saves the photos your Roborock takes of obstacles and pets into Home Assistant's media folder, and exposes the latest ones as entities. Works fully locally, including with [local_roborock_server](https://github.com/Python-roborock/local_roborock_server).

It piggybacks on the core [Roborock integration](https://www.home-assistant.io/integrations/roborock/): after each map update it reads the obstacles the robot photographed, downloads any photo it hasn't seen yet (the 285×285 crop), and keeps it.

Tested on a Qrevo Edge 3 Pro (`roborock.vacuum.a296`). Robots without obstacle photos are skipped.

## Install

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/paulleonartcalvo/roborock-obstacle-photos` as **Integration**.
2. Download **Roborock Obstacle Photos** and restart Home Assistant.
3. Settings → Devices & services → **Add integration** → **Roborock Obstacle Photos**.

The core Roborock integration must be set up first. Photo capture must be enabled on the robot (it is by default on camera models).

## What you get

Entities are added to the existing vacuum device:

| Entity | What it is |
|---|---|
| `image.<vacuum>_latest_obstacle_photo` | Newest photo of anything |
| `image.<vacuum>_latest_pet_photo` | Newest photo the robot labelled as a pet |
| `sensor.<vacuum>_photographed_obstacles` | Photographed obstacles on the current map; attributes list label, type, position and photo id |
| `media_player.<vacuum>_photo_gallery` | Photo gallery: shows the newest photo; **Browse media** opens all saved photos and picking one shows it |
| `button.<vacuum>_refresh_obstacle_photos` | Fetch the map and any new photos now |

The gallery is hidden from voice assistants by default.

Every photo is saved under `/media/roborock_obstacle_photos/<vacuum>/<date>/`. Browse them in **Media → Roborock Obstacle Photos**, which has a **Pets** folder and one folder per day.

Each new photo fires a `roborock_obstacle_photos_new_photo` event with `label`, `type`, `is_pet`, `confidence`, `x`, `y`, `captured_at`, `path` and `media_content_id`.

## Photo pins on the vacuum map

The integration ships a dashboard card (no separate install) that hosts a [Xiaomi Vacuum Map Card](https://github.com/PiotrMachowski/lovelace-xiaomi-vacuum-map-card) and adds a pin for every photographed obstacle to its map. Pins pan and zoom with the map; tap one to see the photo. Zone, room and go-to cleaning keep working as before.

Wrap your existing map card config under `map_card`:

```yaml
type: custom:roborock-obstacle-map-card
map_card:
  type: custom:xiaomi-vacuum-map-card
  vacuum_platform: Roborock
  entity: vacuum.qrevo_edge_3_pro
  map_source:
    camera: image.qrevo_edge_3_pro_map_0_custom
  calibration_source:
    camera: true
```

The map image needs calibration points, such as the one from [Roborock Custom Map](https://github.com/Python-roborock/RoborockCustomMap).

| Option | Default | |
|---|---|---|
| `map_card` | required | Your Xiaomi Vacuum Map Card config |
| `show` | `current` | `current` (last run), `all` (every saved photo) or `off`; the paw button on the map cycles through them |
| `vacuum` | first | Vacuum name or DUID, if you have several |
| `map_entity` | `map_card.map_source.camera` | Map image entity with `calibration_points` |

After installing or updating, reload the browser so the card's script is picked up.

## Example: send pet photos to your phone

```yaml
automation:
  - alias: Robot spotted the cat
    triggers:
      - trigger: event
        event_type: roborock_obstacle_photos_new_photo
        event_data:
          is_pet: true
    actions:
      - action: notify.mobile_app_your_phone
        data:
          message: "The robot spotted the cat"
          data:
            image: /api/image_proxy/image.qrevo_edge_3_pro_latest_pet_photo
```

## Notes

- The pins rely on the Xiaomi card's internal layout (`#map-zoomer-content`); a major update of that card could need a fix here.
- Obstacle labels come from vacuum-map-parser-roborock and Valetudo (which tells cats from dogs). Codes neither lists show as `unknown (<code>)`; `69` is labelled `box` from a photo taken by a Qrevo Edge 3 Pro.

- Uses internals of the core Roborock integration, so a Home Assistant update can break it.
- The robot only keeps photos for obstacles on its current map; this integration keeps them after they disappear from the robot.
- The full 640×480 frame is not fetched (python-roborock does not reassemble it yet).
- **Configure** the integration to choose which **obstacle types** to save and show (e.g. only `pet`) and how many days to **keep photos** (0 = forever). Cleanup runs every 6 hours and after each map update; photos still on the robot's current map are always kept.
