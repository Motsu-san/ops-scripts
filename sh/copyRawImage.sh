# RAW画像をコピー
raw_image_dir="/Volumes/Untitled/DCIM/100MSDCF"
if [ ! -d "$raw_image_dir" ]; then
  echo "Error: Directory $raw_image_dir does not exist."
  exit 1
fi
mv -v $raw_image_dir/*.ARW $target_dir/
