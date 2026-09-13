const std = @import("std");
const builtin = @import("builtin");

pub fn build(b: *std.Build) void {
    const required_zig = std.mem.trim(u8, @embedFile(".zigversion"), "\r\n");
    if (!std.mem.eql(u8, builtin.zig_version_string, required_zig)) {
        std.debug.panic("Fixer pins Zig {s}; selected compiler is {s}", .{
            required_zig, builtin.zig_version_string,
        });
    }
    const optimize = b.standardOptimizeOption(.{});
    const target = b.standardTargetOptionsQueryOnly(.{});
    const bun = b.option([]const u8, "bun", "Bun executable for deterministic TUI tests") orelse "bun";
    const host_args: []const []const u8 = &.{
        b.fmt("-Doptimize={s}", .{@tagName(optimize)}),
        b.fmt("-Dtarget={s}", .{target.zigTriple(b.allocator) catch @panic("OOM")}),
        b.fmt("-Dcpu={s}", .{target.serializeCpuAlloc(b.allocator) catch @panic("OOM")}),
        "-Dorchestration=custom",
        b.fmt("-Dorchestration-root={s}", .{b.path("src/extension.zig").getPath(b)}),
    };

    // The pinned host owns compiler flags, module wiring, and test collection.
    // Invoke its build from its own root; never duplicate its executable setup.
    const host_build = host_command(b, &.{}, host_args);
    const install = b.addInstallBinFile(b.path("vendor/fx/zig-out/bin/fx"), "fx");
    install.step.dependOn(&host_build.step);
    b.getInstallStep().dependOn(&install.step);

    const focused = host_command(b, &.{"test-orchestration-extension"}, host_args);
    focused.step.dependOn(b.getInstallStep());
    b.step("test", "Run Fixer, host contract, and focused host integration unit tests").dependOn(&focused.step);

    const host_tests = host_command(b, &.{"test"}, host_args);
    host_tests.step.dependOn(&focused.step);
    b.step("test-host", "Run the full fx unit suite with this Fixer extension").dependOn(&host_tests.step);

    const tui = b.addSystemCommand(&.{ bun, "test", "--max-concurrency", "1", "./tui-orchestration-extension.test.ts" });
    tui.setCwd(b.path("tests/e2e"));
    tui.setEnvironmentVariable("FX_ORCHESTRATION_E2E", "1");
    tui.setEnvironmentVariable("FX_REQUIRE_TMUX", "1");
    tui.setEnvironmentVariable("FX_E2E_DISABLE_DOTENV", "1");
    tui.step.dependOn(b.getInstallStep());
    b.step("test-e2e", "Exercise the assembled binary through real TTYs and local providers").dependOn(&tui.step);
    const crucible = b.step("crucible-host", "Build and run focused unit and deterministic TUI tests");
    crucible.dependOn(&focused.step);
    crucible.dependOn(&tui.step);

    const run = b.addSystemCommand(&.{b.getInstallPath(.bin, "fx")});
    run.step.dependOn(b.getInstallStep());
    if (b.args) |args| run.addArgs(args);
    b.step("run", "Run the freshly assembled fx with Fixer").dependOn(&run.step);
}

fn host_command(b: *std.Build, steps: []const []const u8, args: []const []const u8) *std.Build.Step.Run {
    const command = b.addSystemCommand(&.{ b.graph.zig_exe, "build" });
    command.addArgs(steps);
    command.addArgs(args);
    command.setCwd(b.path("vendor/fx"));
    command.stdio = .inherit;
    return command;
}
