import 'dart:typed_data';

import 'package:image_picker/image_picker.dart';

typedef GalleryPicker = Future<List<GalleryImage>> Function();

class GalleryException implements Exception {
  const GalleryException(this.message);

  final String message;
}

class GalleryImage {
  const GalleryImage(this.bytes, {required this.png});

  final Uint8List bytes;
  final bool png;
}

class OrderGallery {
  final _picker = ImagePicker();

  Future<List<GalleryImage>> pick() async => _validate(
    await _picker.pickMultiImage(limit: 3, requestFullMetadata: false),
  );

  Future<List<GalleryImage>> recover() async {
    final lost = await _picker.retrieveLostData();
    if (lost.exception case final error?) throw error;
    return _validate(lost.files ?? []);
  }

  Future<List<GalleryImage>> _validate(List<XFile> files) async {
    if (files.length > 3) {
      throw const GalleryException('사진을 1~3장 골라 주세요.');
    }
    return [for (final file in files) await _read(file)];
  }

  Future<GalleryImage> _read(XFile file) async {
    if (await file.length() > 5 * 1024 * 1024) {
      throw const GalleryException('이미지 한 장은 5MB 이하여야 해요.');
    }
    final bytes = await file.readAsBytes();
    const pngHeader = [137, 80, 78, 71, 13, 10, 26, 10];
    final png =
        bytes.length >= pngHeader.length &&
        List.generate(
          pngHeader.length,
          (i) => bytes[i] == pngHeader[i],
        ).every((matches) => matches);
    final jpeg =
        bytes.length >= 3 &&
        bytes[0] == 255 &&
        bytes[1] == 216 &&
        bytes[2] == 255;
    if (!png && !jpeg) {
      throw const GalleryException('JPG 또는 PNG 주문 화면을 골라 주세요.');
    }
    return GalleryImage(bytes, png: png);
  }
}
