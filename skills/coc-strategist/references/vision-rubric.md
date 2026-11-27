# Multimodal Vision & API Fusion Rubric

The official Clash of Clans API exposes offense (`troops`, `spells`, `heroes`, `heroEquipment`, `pets`) but is blind to defense levels, wall levels, trap locations, Inferno modes, Sweeper angles, and base layouts. Vision inspection fills this gap.

## Vision Rubric Checklist

Extract these features systematically from any base screenshot:

| Category | Specific Check | Strategic Impact |
| :--- | :--- | :--- |
| **Town Hall** | Level, position (center/offset), weapon level | Determines which TH-band meta applies |
| **Inferno Towers** | Count, Single vs Multi mode, compartment placement | Single → anti-tank (avoid Golem/PEKKA lead); Multi → anti-swarm (avoid Witches/Bats) |
| **Eagle Artillery / Monolith** | Position, range coverage, exposed vs walled | Dictates whether Blizzard/Zap can snipe it pre-attack |
| **Scattershots** | Count, position relative to core | Threatens Healer-based strategies (Queen Walk) |
| **Air Sweepers** | Count, facing direction | Determines safe air entry side |
| **Air Defenses** | Count, clustering vs spread | Clustered → Lightning value; Spread → LavaLoon pathing |
| **X-Bows** | Ground-only vs Ground+Air mode | Ground-only → air attack is safer |
| **Clan Castle** | Position, lureability (how many tiles from edge) | Easy lure → plan CC kill phase; Hard lure → bring Poison + plan around it |
| **Walls** | Level band estimate (color), compartment depth | Determines siege machine choice and funnel investment |
| **Hero Altars** | Visible levels (if screenshot shows them) | Enemy hero strength assessment |

## Fusion Gate Safety Rule

> [!CAUTION]
> **Never recommend a troop, spell, siege, or equipment that the attacker has not unlocked or is currently upgrading.** Every visual recommendation must be cross-validated against `GET /players/{attacker_tag}`. If the user has not provided their `#TAG`, the output must include: *"⚠️ This army comp assumes max TH{X} troops. Share your #TAG so I can verify your actual levels."*

## Branch Workflows

### Branch 1: Enemy War Base

- **Vision Pass:**
  - TH tier & position
  - Infernos: Single vs Multi
  - Eagle / Monolith / Scattershots
  - Sweeper facing direction
  - Air Defense clustering
  - CC lureability
  - Dead-zone funnels
  - Walls: level band estimate
- **API Pass:**
  - Fetch `GET /players/{attacker_tag}` to retrieve the attacker's actual troop, spell, hero, equipment, and pet levels.
- **Fusion Gate:**
  - Cross-validate every visually ideal troop, spell, siege, and equipment against the attacker's unlocked and available levels.
- **Output:**
  - Tailored Army Comp
  - Spell Count & Timing
  - Hero Equipment Loadout
  - Phase-by-Phase Attack Plan (Funnel → Entry → Core → Cleanup)
  - Clock-Position Deployment

### Branch 2: Own Village / Builder

- **Vision Pass:**
  - Defense & wall levels
  - Hero altars (upgrading?)
  - Builder count / idle builders
- **API Pass:**
  - Fetch `GET /players/{own_tag}` to extract Lab, Hero, Equipment, and Pet deficits.
- **Output:**
  - Prioritized Builder Queue
  - Lab Research Plan
  - Ore/Equipment Allocation
  - CWL Availability Forecast
