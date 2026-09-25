require 'sketchup.rb'
require_relative 'sketchup_mcp_bridge/bridge_server'
require_relative 'sketchup_mcp_bridge/geometry'
require_relative 'sketchup_mcp_bridge/preview'

module SketchupMcpBridge
  def self.start
    Server.instance.start
  end

  def self.stop
    Server.instance.stop
  end
end

module Kernel
  define_method(:MCPSTART) do
    SketchupMcpBridge.start
  end

  define_method(:MCPSTOP) do
    SketchupMcpBridge.stop
  end
end

def mcpstart
  SketchupMcpBridge.start
end

def mcpstop
  SketchupMcpBridge.stop
end

unless file_loaded?(__FILE__)
  UI.add_context_menu_handler { |_menu| }
  file_loaded(__FILE__)
end

unless defined?(@sketchup_mcp_commands_bound) && @sketchup_mcp_commands_bound
  start_command = UI::Command.new('MCPSTART') { SketchupMcpBridge.start }
  stop_command = UI::Command.new('MCPSTOP') { SketchupMcpBridge.stop }

  UI.menu('Plugins').add_item(start_command)
  UI.menu('Plugins').add_item(stop_command)
  @sketchup_mcp_commands_bound = true
end
