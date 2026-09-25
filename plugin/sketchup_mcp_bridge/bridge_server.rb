require 'json'
require 'securerandom'
require 'singleton'
require 'thread'
require 'timeout'
require 'webrick'

module SketchupMcpBridge
  class BridgeError < StandardError
    attr_reader :code, :status

    def initialize(message, code: 'sketchup_error', status: 500)
      super(message)
      @code = code
      @status = status
    end
  end

  class Server
    include Singleton

    HOST = '127.0.0.1'.freeze
    PORT = 8766
    REQUEST_TIMEOUT_SECONDS = 25

    def initialize
      @token = ENV['SKETCHUP_MCP_TOKEN'].to_s.strip
      @token = SecureRandom.hex(24) if @token.empty?
      @queue = Queue.new
      @mutex = Mutex.new
      @server = nil
      @thread = nil
      @timer_id = nil
    end

    attr_reader :token

    def start
      @mutex.synchronize do
        return if running?

        start_timer
        @server = WEBrick::HTTPServer.new(
          BindAddress: HOST,
          Port: PORT,
          Logger: WEBrick::Log.new($stderr, WEBrick::Log::WARN),
          AccessLog: []
        )
        mount_routes(@server)
        @thread = Thread.new { @server.start }
      end

      puts "SketchUp MCP bridge listening at http://#{HOST}:#{PORT}/"
      puts "SKETCHUP_MCP_TOKEN=#{@token}"
      true
    end

    def stop
      server = nil
      thread = nil
      timer_id = nil

      @mutex.synchronize do
        server = @server
        thread = @thread
        timer_id = @timer_id
        @server = nil
        @thread = nil
        @timer_id = nil
      end

      server&.shutdown
      thread&.join(2)
      UI.stop_timer(timer_id) if timer_id
      puts 'SketchUp MCP bridge stopped'
      true
    end

    def running?
      @server && @thread && @thread.alive?
    end

    private

    def start_timer
      return if @timer_id

      @timer_id = UI.start_timer(0.05, true) { drain_queue }
    end

    def mount_routes(server)
      server.mount_proc('/') do |request, response|
        handle_request(request, response)
      end
    end

    def handle_request(request, response)
      response['Content-Type'] = 'application/json'

      unless request.request_method == 'POST'
        write_json(response, 405, 'error' => 'method not allowed', 'code' => 'method_not_allowed')
        return
      end

      unless authorized?(request)
        write_json(response, 401, 'error' => 'unauthorized', 'code' => 'unauthorized')
        return
      end

      json = parse_json(request.body.to_s)
      result = dispatch_on_main_thread(clean_path(request.path), json)
      write_json(response, result.fetch(:status, 200), result.fetch(:body))
    rescue JSON::ParserError => e
      write_json(response, 400, 'error' => e.message, 'code' => 'bad_json')
    rescue Timeout::Error
      write_json(response, 504, 'error' => 'SketchUp operation timed out', 'code' => 'timeout')
    rescue StandardError => e
      write_json(response, 500, 'error' => e.message, 'code' => 'server_error')
    end

    def authorized?(request)
      request['Authorization'].to_s == "Bearer #{@token}"
    end

    def parse_json(body)
      body.empty? ? {} : JSON.parse(body)
    end

    def clean_path(path)
      path.to_s.sub(%r{\A/+}, '').sub(%r{/+\z}, '')
    end

    def dispatch_on_main_thread(path, json)
      result_queue = Queue.new
      @queue << { path: path, json: json, result_queue: result_queue }
      Timeout.timeout(REQUEST_TIMEOUT_SECONDS) { result_queue.pop }
    end

    def drain_queue
      until @queue.empty?
        request = @queue.pop(true)
        request[:result_queue] << route(request[:path], request[:json])
      end
    rescue ThreadError
      nil
    rescue StandardError => e
      request[:result_queue] << error_result(e) if request && request[:result_queue]
    end

    def route(path, json)
      body =
        case path
        when 'health' then Geometry.health
        when 'model/info' then Geometry.model_info
        when 'plan/extrude' then Geometry.extrude(json)
        when 'elements/list' then Geometry.list_elements
        when 'walls/height' then Geometry.set_wall_height(json)
        when 'roof' then Geometry.add_roof(json)
        when 'preview/capture' then Preview.capture(json)
        else
          return { status: 404, body: { 'error' => "unknown path #{path}", 'code' => 'unknown_path' } }
        end

      { status: 200, body: body }
    rescue BridgeError => e
      { status: e.status, body: { 'error' => e.message, 'code' => e.code } }
    rescue StandardError => e
      { status: 500, body: { 'error' => e.message, 'code' => 'sketchup_error' } }
    end

    def error_result(error)
      status = error.respond_to?(:status) ? error.status : 500
      code = error.respond_to?(:code) ? error.code : 'sketchup_error'
      { status: status, body: { 'error' => error.message, 'code' => code } }
    end

    def write_json(response, status, body)
      response.status = status
      response.body = JSON.generate(body)
    end
  end
end
