//! Makes what the exe carries: the tool's wheel with its dependencies pinned, its Agent Skill, the icon, and what
//! Windows shows about the exe. The version, the wheel, the skill, and the icon all come from the repository, so
//! nothing is kept in step by hand.

use std::error::Error;
use std::ffi::OsStr;
use std::fs::{self, File};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::{env, io};

use resvg::tiny_skia::{BlendMode, FillRule, Paint, PathBuilder, Pixmap, PremultipliedColorU8, Transform};
use resvg::usvg;
use winresource::{VersionInfo, WindowsResource};

const APP_NAME: &str = "3D Modeling";
const EXE_NAME: &str = "Modeling3DSetup.exe";
const ICON: &str = "app/public/favicon.svg";
// Every size Windows draws the icon at, from the tray at 100% scaling to the large tiles.
const ICON_SIZES: [u16; 8] = [16, 20, 24, 32, 40, 48, 64, 256];
// The icon with a dot on it, which the tray shows when a newer version is out. The app asks for it by this id.
const UPDATE_ICON_ID: &str = "2";
// The dot's radius, and the gap that keeps it apart from the icon, as parts of the icon's width.
const DOT_RADIUS: f32 = 0.21;
const DOT_GAP: f32 = 0.07;
// The app's accent color.
const DOT_COLOR: [u8; 3] = [0x6a, 0xb3, 0xee];
const PYTHON_VERSION: &str = ".python-version";
// The tool's Agent Skill, which agents are given through the skills CLI.
const SKILL: &str = "skills/modeling-3d/SKILL.md";
// What the wheel and its pins are made from.
const WHEEL_SOURCES: [&str; 5] = ["pyproject.toml", "uv.lock", "README.md", "LICENSE", "src"];

type Outcome<T> = Result<T, Box<dyn Error>>;

fn main() -> Outcome<()> {
    let crate_dir = PathBuf::from(variable("CARGO_MANIFEST_DIR")?);
    let repository = crate_dir.parent().ok_or("The crate has no parent folder.")?;
    let out = PathBuf::from(variable("OUT_DIR")?);

    for source in WHEEL_SOURCES.iter().chain([&ICON, &PYTHON_VERSION, &SKILL]) {
        println!("cargo:rerun-if-changed={}", repository.join(source).display());
    }
    println!("cargo:rerun-if-changed=app.manifest");

    let project: toml::Table = fs::read_to_string(repository.join("pyproject.toml"))?.parse()?;
    let version = project_text(&project, &["version"])?;
    println!("cargo:rustc-env=APP_NAME={APP_NAME}");
    println!("cargo:rustc-env=APP_VERSION={version}");
    println!("cargo:rustc-env=APP_REPOSITORY={}", project_text(&project, &["urls", "Repository"])?);
    // The Python the tool is developed on, which is the one it is installed on.
    let python = fs::read_to_string(repository.join(PYTHON_VERSION))?;
    println!("cargo:rustc-env=PYTHON_VERSION={}", python.trim());
    println!("cargo:rustc-env=SKILL_PATH={}", repository.join(SKILL).display());

    let wheel = build_wheel(repository, &out.join("wheel"))?;
    let wheel_name = wheel.file_name().and_then(OsStr::to_str).ok_or("The wheel has no name.")?;
    println!("cargo:rustc-env=WHEEL_PATH={}", wheel.display());
    println!("cargo:rustc-env=WHEEL_NAME={wheel_name}");

    let constraints = out.join("constraints.txt");
    export_constraints(repository, &constraints)?;
    println!("cargo:rustc-env=CONSTRAINTS_PATH={}", constraints.display());

    let icon = out.join("icon.ico");
    write_icon(&repository.join(ICON), &icon, false)?;
    let update_icon = out.join("icon-update.ico");
    write_icon(&repository.join(ICON), &update_icon, true)?;

    let numbers = version_numbers(version);
    WindowsResource::new()
        .set_icon(icon.to_str().ok_or("The icon's path is not Unicode.")?)
        .set_icon_with_id(update_icon.to_str().ok_or("The icon's path is not Unicode.")?, UPDATE_ICON_ID)
        .set_manifest_file("app.manifest")
        .set("ProductName", APP_NAME)
        .set("FileDescription", APP_NAME)
        .set("CompanyName", &variable("CARGO_PKG_AUTHORS")?)
        .set("OriginalFilename", EXE_NAME)
        .set("ProductVersion", version)
        .set("FileVersion", version)
        .set_version_info(VersionInfo::PRODUCTVERSION, numbers)
        .set_version_info(VersionInfo::FILEVERSION, numbers)
        .compile()?;
    Ok(())
}

fn variable(name: &str) -> Outcome<String> {
    env::var(name).map_err(|error| format!("{name}: {error}").into())
}

/// Returns the text at a path of keys under `[project]` in `pyproject.toml`.
fn project_text<'a>(pyproject: &'a toml::Table, keys: &[&str]) -> Outcome<&'a str> {
    let mut value = pyproject.get("project");
    for key in keys {
        value = value.and_then(|table| table.get(key));
    }
    value
        .and_then(toml::Value::as_str)
        .ok_or_else(|| format!("pyproject.toml has no project.{}.", keys.join(".")).into())
}

/// The version as the four 16 bit numbers Windows keeps beside the text, from the numbers the version starts with.
fn version_numbers(version: &str) -> u64 {
    version
        .split('.')
        .map(|part| part.chars().take_while(char::is_ascii_digit).collect::<String>())
        .map(|digits| digits.parse::<u16>().unwrap_or(0))
        .chain([0; 4])
        .take(4)
        .fold(0, |numbers, part| numbers << 16 | u64::from(part))
}

fn build_wheel(repository: &Path, folder: &Path) -> Outcome<PathBuf> {
    // A wheel left from an earlier version would make two to pick from.
    match fs::remove_dir_all(folder) {
        Err(error) if error.kind() != io::ErrorKind::NotFound => return Err(error.into()),
        _ => {}
    }
    uv(repository, &["build", "--wheel", "--out-dir"], folder)?;
    let mut wheels = Vec::new();
    for entry in fs::read_dir(folder)? {
        let path = entry?.path();
        if path.extension() == Some(OsStr::new("whl")) {
            wheels.push(path);
        }
    }
    match <[PathBuf; 1]>::try_from(wheels) {
        Ok([wheel]) => Ok(wheel),
        Err(wheels) => Err(format!("uv build made {} wheels in {}, not one.", wheels.len(), folder.display()).into()),
    }
}

/// Writes the versions `uv.lock` has for the tool's dependencies, for `uv tool install` to keep to, with those of every
/// agent provider, which are extras and otherwise not pinned at all. Their hashes are left out, since
/// `uv tool install` doesn't check them.
fn export_constraints(repository: &Path, file: &Path) -> Outcome<()> {
    let arguments = [
        "export",
        "--frozen",
        "--no-default-groups",
        "--all-extras",
        "--no-emit-project",
        "--no-header",
        "--no-annotate",
        "--no-hashes",
        "--format",
        "requirements-txt",
        "--output-file",
    ];
    uv(repository, &arguments, file)
}

fn uv(repository: &Path, arguments: &[&str], last: &Path) -> Outcome<()> {
    let output = Command::new("uv")
        .args(arguments)
        .arg(last)
        .current_dir(repository)
        .output()
        .map_err(|error| format!("uv could not be run, and the build needs it: {error}"))?;
    if output.status.success() {
        return Ok(());
    }
    Err(format!("uv {} failed.\n{}", arguments.join(" "), String::from_utf8_lossy(&output.stderr)).into())
}

fn write_icon(svg: &Path, ico: &Path, dot: bool) -> Outcome<()> {
    let tree = usvg::Tree::from_data(&fs::read(svg)?, &usvg::Options::default())?;
    let mut icon = ico::IconDir::new(ico::ResourceType::Icon);
    for size in ICON_SIZES {
        let mut pixmap = Pixmap::new(size.into(), size.into()).ok_or("An icon size is zero.")?;
        let scale = f32::from(size) / tree.size().width();
        resvg::render(&tree, Transform::from_scale(scale, scale), &mut pixmap.as_mut());
        if dot {
            draw_dot(&mut pixmap, f32::from(size))?;
        }
        // The renderer's colors are multiplied by their alpha, and an icon's are not.
        let rgba = pixmap
            .pixels()
            .iter()
            .map(PremultipliedColorU8::demultiply)
            .flat_map(|color| [color.red(), color.green(), color.blue(), color.alpha()])
            .collect();
        let image = ico::IconImage::from_rgba_data(size.into(), size.into(), rgba);
        icon.add_entry(ico::IconDirEntry::encode(&image)?);
    }
    icon.write(File::create(ico)?)?;
    Ok(())
}

/// Draws a dot in the top right corner of an icon of this width, over a gap cut out of the icon around it.
fn draw_dot(icon: &mut Pixmap, size: f32) -> Outcome<()> {
    let dot = size * DOT_RADIUS;
    let mut paint = Paint { anti_alias: true, ..Paint::default() };
    let [red, green, blue] = DOT_COLOR;
    paint.set_color_rgba8(red, green, blue, u8::MAX);
    for (radius, blend_mode) in [(dot + size * DOT_GAP, BlendMode::Clear), (dot, BlendMode::SourceOver)] {
        let circle = PathBuilder::from_circle(size - dot, dot, radius).ok_or("The icon's dot has no size.")?;
        paint.blend_mode = blend_mode;
        icon.fill_path(&circle, &paint, FillRule::Winding, Transform::identity(), None);
    }
    Ok(())
}
