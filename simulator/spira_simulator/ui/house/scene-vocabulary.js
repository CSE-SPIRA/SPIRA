// Renderer fields from slots.json. The parity test covers the shell asset copy.
export default [
  {"id": "balloon", "kind": "goods", "parameters": {"palette": {"enum": ["pink_white_gold", "princess_pink", "ocean_blue", "sunny_yellow"], "default": "pink_white_gold"}, "placement": {"enum": ["bunch", "floor"], "default": "bunch"}, "count": {"type": "integer", "minimum": 1, "maximum": 8, "default": 5}}, "anchors": ["living_room"]},
  {"id": "party_hat", "kind": "goods", "parameters": {"count": {"type": "integer", "minimum": 1, "maximum": 8, "default": 3}}, "anchors": ["kitchen"]},
  {"id": "cake_topper", "kind": "goods", "parameters": {}, "anchors": ["kitchen"]},
  {"id": "strawberry", "kind": "goods", "parameters": {"placement": {"enum": ["fridge", "counter"], "default": "fridge"}}, "anchors": ["fridge_01", "kitchen"]},
  {"id": "cream", "kind": "goods", "parameters": {"placement": {"enum": ["fridge", "counter"], "default": "fridge"}}, "anchors": ["fridge_01", "kitchen"]},
  {"id": "child", "kind": "person", "parameters": {"skin": {"enum": ["peach", "tan", "brown"], "default": "peach"}, "outfit": {"enum": ["princess_pink", "ocean_blue", "forest_green", "sunny_yellow"], "default": "princess_pink"}}, "anchors": ["living_room"]},
  {"id": "guest_child", "kind": "person", "parameters": {"variant": {"enum": ["bob", "curls", "crop"], "default": "bob"}, "skin": {"enum": ["peach", "tan", "brown"], "default": "tan"}, "outfit": {"enum": ["princess_pink", "ocean_blue", "forest_green", "sunny_yellow"], "default": "ocean_blue"}}, "anchors": ["entrance", "living_room"]},
  {"id": "adult", "kind": "person", "parameters": {"skin": {"enum": ["peach", "tan", "brown"], "default": "peach"}, "outfit": {"enum": ["princess_pink", "ocean_blue", "forest_green", "sunny_yellow"], "default": "forest_green"}}, "anchors": ["entrance", "living_room"]},
  {"id": "confetti", "kind": "effect", "parameters": {"count": {"enum": [12, 24, 36], "default": 24}}, "anchors": ["living_room"]},
  {"id": "ceiling_cove", "kind": "effect", "parameters": {}, "anchors": ["light_01", "living_room"]},
  {"id": "banner", "kind": "surface", "parameters": {"color": {"enum": ["princess_pink", "ocean_blue", "sunny_yellow"], "default": "princess_pink"}, "artwork": {"type": ["string", "null"], "format": "uri-reference", "minLength": 1, "default": null}}, "anchors": ["living_room"]},
  {"id": "cleaner_sweep", "kind": "motion", "parameters": {}, "anchors": ["cleaner_01", "living_room"]},
  {"id": "guests_enter", "kind": "motion", "parameters": {}, "anchors": ["entrance", "living_room"]},
  {"id": "light_spread", "kind": "motion", "parameters": {"color": {"enum": ["princess_pink", "ocean_blue", "sunny_yellow"], "default": "princess_pink"}}, "anchors": ["light_01", "living_room"]},
];
