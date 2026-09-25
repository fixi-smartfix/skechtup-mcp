require 'base64'
require 'tmpdir'

module SketchupMcpBridge
  module Preview
    module_function

    def capture(payload)
      max_width = (payload['max_width'] || 1600).to_i
      max_width = 1600 if max_width <= 0
      path = File.join(Dir.tmpdir, "fixi_sketchup_preview_#{Time.now.to_i}_#{rand(100_000)}.png")
      view = Sketchup.active_model.active_view

      if view.respond_to?(:write_image)
        write_image(view, path, max_width)
      else
        raise BridgeError.new('active view cannot write image', code: 'preview_unavailable', status: 500)
      end

      bytes = File.binread(path)
      { 'png_base64' => Base64.strict_encode64(bytes) }
    ensure
      File.delete(path) if path && File.exist?(path)
    end

    def write_image(view, path, max_width)
      width = [max_width, 400].max
      options = {
        filename: path,
        width: width,
        height: (width * 0.75).to_i,
        antialias: true,
        transparent: false
      }

      begin
        view.write_image(options)
      rescue TypeError
        view.write_image(path)
      end
    end
  end
end
