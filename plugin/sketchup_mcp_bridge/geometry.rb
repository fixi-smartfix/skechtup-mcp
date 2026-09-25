module SketchupMcpBridge
  module Geometry
    MM = 25.4
    FIXI = /^FIXI_/.freeze
    DICT = 'FIXI'.freeze
    LENGTH_UNIT_MM = 2

    COLORS = {
      'exterior' => [80, 80, 80],
      'interior' => [190, 190, 190],
      'structural' => [135, 92, 45],
      'opening' => [120, 150, 190],
      'slab' => [170, 170, 170],
      'roof' => [90, 90, 90]
    }.freeze

    module_function

    def mm(value)
      value.to_f / MM
    end

    def health
      model = Sketchup.active_model
      {
        'ok' => true,
        'product' => 'SketchUp',
        'model' => model.title.to_s,
        'units' => units_name(model)
      }
    end

    def model_info
      model = Sketchup.active_model
      {
        'name' => model.title.to_s,
        'path' => model.path.to_s,
        'units' => units_name(model),
        'fixi_counts' => fixi_counts(model)
      }
    end

    def extrude(payload)
      model = Sketchup.active_model
      walls = Array(payload['walls'])
      raise BridgeError.new('no walls', code: 'no_walls', status: 500) if walls.empty?

      openings = Array(payload['openings'])
      warnings = Array(payload['warnings'])
      slab = payload['slab'] || slab_from_walls(walls)
      units_changed = ensure_mm_units(model)

      created_walls = 0
      created_openings = 0
      created_slab = false

      model.start_operation('FIXI plan extrude', true)
      begin
        clear_fixi(model)
        walls.each do |wall|
          created_walls += 1 if create_wall_group(model, wall)
        end
        openings.each do |opening|
          created_openings += 1 if create_opening_group(model, opening)
        end
        created_slab = !!create_slab_group(model, slab)
        model.commit_operation
      rescue StandardError
        model.abort_operation
        raise
      end

      result = {
        'created' => true,
        'walls' => created_walls,
        'openings' => created_openings,
        'slab' => created_slab,
        'warnings' => warnings
      }
      result['units_changed'] = true if units_changed
      result
    end

    def list_elements
      walls = []
      openings = []
      slab = nil
      roof = nil

      fixi_entities(Sketchup.active_model).each do |entity|
        attrs = attrs_for(entity)
        name = entity.name.to_s
        attrs['name'] = name

        case name
        when /^FIXI_WALL_/
          walls << attrs
        when /^FIXI_DOOR_/, /^FIXI_WINDOW_/
          openings << attrs
        when 'FIXI_SLAB'
          slab = attrs
        when 'FIXI_ROOF'
          roof = attrs
        end
      end

      { 'walls' => walls, 'openings' => openings, 'slab' => slab, 'roof' => roof }
    end

    def set_wall_height(payload)
      wall_id = payload['wall_id'].to_s
      height_mm = payload['height_mm'].to_f
      raise BridgeError.new('height_mm must be positive', code: 'invalid_height', status: 400) unless height_mm.positive?

      model = Sketchup.active_model
      targets =
        if wall_id == 'all'
          fixi_entities(model).select { |entity| entity.name.to_s.start_with?('FIXI_WALL_') }
        else
          [find_fixi(model, "FIXI_WALL_#{wall_id}")].compact
        end

      raise BridgeError.new('wall not found', code: 'wall_not_found', status: 500) if targets.empty?

      rebuilt_ids = []
      model.start_operation('FIXI wall height', true)
      begin
        targets.each do |group|
          attrs = attrs_for(group)
          wall = attrs.merge('height_mm' => height_mm)
          rebuilt_ids << wall['wall_id'].to_s
          group.erase!
          create_wall_group(model, wall)
        end
        model.commit_operation
      rescue StandardError
        model.abort_operation
        raise
      end

      { 'updated' => rebuilt_ids.length, 'wall_ids' => rebuilt_ids }
    end

    def add_roof(payload)
      kind = (payload['kind'] || 'flat').to_s
      overhang_mm = (payload['overhang_mm'] || 400).to_f
      pitch_deg = (payload['pitch_deg'] || 30).to_f
      raise BridgeError.new('invalid roof kind', code: 'invalid_roof_kind', status: 400) unless %w[flat gable].include?(kind)

      model = Sketchup.active_model
      walls = fixi_entities(model).select { |entity| entity.name.to_s.start_with?('FIXI_WALL_') }
      raise BridgeError.new('no walls', code: 'no_walls', status: 500) if walls.empty?

      bbox = roof_bbox(model, walls, overhang_mm)
      max_height_mm = walls.map { |wall| attrs_for(wall)['height_mm'].to_f }.max

      model.start_operation('FIXI roof', true)
      begin
        find_fixi(model, 'FIXI_ROOF')&.erase!
        group =
          if kind == 'flat'
            create_flat_roof_group(model, bbox, max_height_mm)
          else
            create_gable_roof_group(model, bbox, max_height_mm, pitch_deg)
          end
        write_attrs(group, 'kind' => kind, 'overhang_mm' => overhang_mm, 'pitch_deg' => pitch_deg, 'height_mm' => max_height_mm)
        model.commit_operation
      rescue StandardError
        model.abort_operation
        raise
      end

      { 'created' => true, 'kind' => kind }
    end

    def clear_fixi(model)
      model.active_entities.to_a.each do |entity|
        next unless fixi_entity?(entity)

        entity.erase!
      end
    end

    def create_wall_group(model, wall)
      x1 = wall['x1'].to_f
      y1 = wall['y1'].to_f
      x2 = wall['x2'].to_f
      y2 = wall['y2'].to_f
      thickness_mm = wall['thickness_mm'].to_f
      height_mm = (wall['height_mm'] || 3000).to_f
      dx = x2 - x1
      dy = y2 - y1
      length = Math.sqrt((dx * dx) + (dy * dy))
      return nil unless length.positive? && thickness_mm.positive? && height_mm.positive?

      ux = dx / length
      uy = dy / length
      px = -uy
      py = ux
      half = thickness_mm / 2.0
      points = [
        point(x1 + (px * half), y1 + (py * half), 0),
        point(x2 + (px * half), y2 + (py * half), 0),
        point(x2 - (px * half), y2 - (py * half), 0),
        point(x1 - (px * half), y1 - (py * half), 0)
      ]

      group = model.active_entities.add_group
      wall_id = wall['wall_id'].to_s
      group.name = "FIXI_WALL_#{wall_id}"
      face = group.entities.add_face(points)
      face.reverse! if face.normal.z < 0
      face.pushpull(mm(height_mm))
      apply_material(model, group, wall['kind'].to_s)
      write_attrs(group, wall.merge('wall_id' => wall_id, 'height_mm' => height_mm, 'class' => 'wall'))
      group
    end

    def create_opening_group(model, opening)
      type = opening['type'].to_s
      name_prefix = type == 'window' ? 'FIXI_WINDOW' : 'FIXI_DOOR'
      opening_id = (opening['opening_id'] || opening['id']).to_s
      x1 = opening['x1'].to_f
      y1 = opening['y1'].to_f
      x2 = opening['x2'].to_f
      y2 = opening['y2'].to_f
      z0 = (opening['z0'] || 0).to_f
      z1 = opening['z1'].to_f
      dx = x2 - x1
      dy = y2 - y1
      length = Math.sqrt((dx * dx) + (dy * dy))
      return nil unless length.positive? && z1 > z0

      ux = dx / length
      uy = dy / length
      px = -uy
      py = ux
      half_leaf_mm = 20.0
      points = [
        point(x1 + (px * half_leaf_mm), y1 + (py * half_leaf_mm), z0),
        point(x2 + (px * half_leaf_mm), y2 + (py * half_leaf_mm), z0),
        point(x2 - (px * half_leaf_mm), y2 - (py * half_leaf_mm), z0),
        point(x1 - (px * half_leaf_mm), y1 - (py * half_leaf_mm), z0)
      ]

      group = model.active_entities.add_group
      group.name = "#{name_prefix}_#{opening_id}"
      face = group.entities.add_face(points)
      face.reverse! if face.normal.z < 0
      face.pushpull(mm(z1 - z0))
      apply_material(model, group, 'opening')
      write_attrs(
        group,
        opening.merge(
          'opening_id' => opening_id,
          'type' => type,
          'leaf_thickness_mm' => 40,
          'class' => type == 'window' ? 'window' : 'door'
        )
      )
      group
    end

    def create_slab_group(model, slab)
      return nil unless slab

      min_x = slab['min_x'].to_f
      min_y = slab['min_y'].to_f
      max_x = slab['max_x'].to_f
      max_y = slab['max_y'].to_f
      thickness_mm = (slab['thickness_mm'] || 150).to_f
      return nil unless max_x > min_x && max_y > min_y && thickness_mm.positive?

      points = [
        point(min_x, min_y, 0),
        point(max_x, min_y, 0),
        point(max_x, max_y, 0),
        point(min_x, max_y, 0)
      ]
      group = model.active_entities.add_group
      group.name = 'FIXI_SLAB'
      face = group.entities.add_face(points)
      face.reverse! if face.normal.z < 0
      face.pushpull(-mm(thickness_mm))
      apply_material(model, group, 'slab')
      write_attrs(group, slab.merge('thickness_mm' => thickness_mm, 'class' => 'slab'))
      group
    end

    def create_flat_roof_group(model, bbox, height_mm)
      points = [
        point(bbox['min_x'], bbox['min_y'], height_mm),
        point(bbox['max_x'], bbox['min_y'], height_mm),
        point(bbox['max_x'], bbox['max_y'], height_mm),
        point(bbox['min_x'], bbox['max_y'], height_mm)
      ]
      group = model.active_entities.add_group
      group.name = 'FIXI_ROOF'
      face = group.entities.add_face(points)
      face.reverse! if face.normal.z < 0
      face.pushpull(mm(100))
      apply_material(model, group, 'roof')
      group
    end

    def create_gable_roof_group(model, bbox, height_mm, pitch_deg)
      min_x = bbox['min_x']
      min_y = bbox['min_y']
      max_x = bbox['max_x']
      max_y = bbox['max_y']
      width_x = max_x - min_x
      width_y = max_y - min_y
      group = model.active_entities.add_group
      group.name = 'FIXI_ROOF'

      if width_x >= width_y
        mid_y = (min_y + max_y) / 2.0
        rise = Math.tan(pitch_deg * Math::PI / 180.0) * (width_y / 2.0)
        a = point(min_x, min_y, height_mm)
        b = point(max_x, min_y, height_mm)
        c = point(max_x, max_y, height_mm)
        d = point(min_x, max_y, height_mm)
        r1 = point(min_x, mid_y, height_mm + rise)
        r2 = point(max_x, mid_y, height_mm + rise)
        add_face(group, [a, b, r2, r1])
        add_face(group, [d, r1, r2, c])
        add_face(group, [a, r1, d])
        add_face(group, [b, c, r2])
      else
        mid_x = (min_x + max_x) / 2.0
        rise = Math.tan(pitch_deg * Math::PI / 180.0) * (width_x / 2.0)
        a = point(min_x, min_y, height_mm)
        b = point(max_x, min_y, height_mm)
        c = point(max_x, max_y, height_mm)
        d = point(min_x, max_y, height_mm)
        r1 = point(mid_x, min_y, height_mm + rise)
        r2 = point(mid_x, max_y, height_mm + rise)
        add_face(group, [a, r1, r2, d])
        add_face(group, [b, c, r2, r1])
        add_face(group, [a, b, r1])
        add_face(group, [d, r2, c])
      end

      apply_material(model, group, 'roof')
      group
    end

    def add_face(group, points)
      face = group.entities.add_face(points)
      face.reverse! if face && face.normal.z < 0
      face
    end

    def roof_bbox(model, walls, overhang_mm)
      slab = find_fixi(model, 'FIXI_SLAB')
      attrs = attrs_for(slab) if slab
      if attrs && attrs['min_x'] && attrs['max_x'] && attrs['min_y'] && attrs['max_y']
        bbox = attrs
      else
        xs = []
        ys = []
        walls.each do |wall|
          wall_attrs = attrs_for(wall)
          xs << wall_attrs['x1'].to_f << wall_attrs['x2'].to_f
          ys << wall_attrs['y1'].to_f << wall_attrs['y2'].to_f
        end
        bbox = { 'min_x' => xs.min, 'min_y' => ys.min, 'max_x' => xs.max, 'max_y' => ys.max }
      end

      {
        'min_x' => bbox['min_x'].to_f - overhang_mm,
        'min_y' => bbox['min_y'].to_f - overhang_mm,
        'max_x' => bbox['max_x'].to_f + overhang_mm,
        'max_y' => bbox['max_y'].to_f + overhang_mm
      }
    end

    def slab_from_walls(walls)
      xs = []
      ys = []
      walls.each do |wall|
        xs << wall['x1'].to_f << wall['x2'].to_f
        ys << wall['y1'].to_f << wall['y2'].to_f
      end
      { 'min_x' => xs.min, 'min_y' => ys.min, 'max_x' => xs.max, 'max_y' => ys.max, 'thickness_mm' => 150 }
    end

    def ensure_mm_units(model)
      options = model.options['UnitsOptions']
      return false unless options

      before = options['LengthUnit']
      return false if before == LENGTH_UNIT_MM

      options['LengthUnit'] = LENGTH_UNIT_MM
      true
    rescue StandardError
      false
    end

    def units_name(model)
      unit = model.options['UnitsOptions']['LengthUnit']
      unit == LENGTH_UNIT_MM ? 'Millimeters' : unit.to_s
    rescue StandardError
      'unknown'
    end

    def fixi_counts(model)
      counts = { 'walls' => 0, 'doors' => 0, 'windows' => 0, 'slab' => 0, 'roof' => 0 }
      fixi_entities(model).each do |entity|
        name = entity.name.to_s
        case name
        when /^FIXI_WALL_/ then counts['walls'] += 1
        when /^FIXI_DOOR_/ then counts['doors'] += 1
        when /^FIXI_WINDOW_/ then counts['windows'] += 1
        when 'FIXI_SLAB' then counts['slab'] += 1
        when 'FIXI_ROOF' then counts['roof'] += 1
        end
      end
      counts
    end

    def fixi_entities(model)
      model.active_entities.to_a.select { |entity| fixi_entity?(entity) }
    end

    def fixi_entity?(entity)
      (defined?(Sketchup::Group) && entity.is_a?(Sketchup::Group) ||
        defined?(Sketchup::ComponentInstance) && entity.is_a?(Sketchup::ComponentInstance)) &&
        entity.respond_to?(:name) &&
        entity.name.to_s.start_with?('FIXI_')
    end

    def find_fixi(model, name)
      fixi_entities(model).find { |entity| entity.name.to_s == name }
    end

    def attrs_for(entity)
      return {} unless entity && entity.attribute_dictionaries

      dict = entity.attribute_dictionaries[DICT]
      attrs = {}
      dict&.each_pair { |key, value| attrs[key.to_s] = value }
      attrs
    end

    def write_attrs(entity, attrs)
      attrs.each do |key, value|
        next if value.nil?

        entity.set_attribute(DICT, key.to_s, value)
      end
    end

    def apply_material(model, group, kind)
      name = "FIXI_#{kind}"
      material = model.materials[name] || model.materials.add(name)
      material.color = Sketchup::Color.new(*COLORS.fetch(kind, COLORS['interior']))
      group.material = material
      group.entities.grep(Sketchup::Face).each { |face| face.material = material }
    end

    def point(x_mm, y_mm, z_mm)
      Geom::Point3d.new(mm(x_mm), mm(y_mm), mm(z_mm))
    end
  end
end
