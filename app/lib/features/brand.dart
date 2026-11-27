// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../design_tokens.g.dart';
import '../korean_text.dart';
import 'labels.dart';

class SpiraMark extends StatelessWidget {
  const SpiraMark({super.key});

  @override
  Widget build(BuildContext context) => const KoreanText(
    'SPIRA',
    maxLines: 1,
    style: TextStyle(
      color: DesignTokens.greenDeep,
      fontSize: DesignTokens.size22,
      fontWeight: FontWeight.w700,
    ),
  );
}

class SpiraTopBar extends StatelessWidget implements PreferredSizeWidget {
  const SpiraTopBar({
    super.key,
    this.showFixtureLabel = false,
    this.onEnterToken,
  });

  final bool showFixtureLabel;
  final VoidCallback? onEnterToken;

  @override
  Size get preferredSize => const Size.fromHeight(kToolbarHeight);

  @override
  Widget build(BuildContext context) => AppBar(
    automaticallyImplyLeading: false,
    excludeHeaderSemantics: true,
    scrolledUnderElevation: 0,
    titleSpacing: DesignTokens.space12,
    title: Row(
      children: [
        Expanded(
          child: showFixtureLabel
              ? KoreanText(
                  fixturePreviewLabel,
                  style: Theme.of(context).textTheme.bodySmall,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                )
              : const SizedBox.shrink(),
        ),
        Semantics(header: true, child: const SpiraMark()),
        Expanded(
          child: Align(
            alignment: Alignment.centerRight,
            child: onEnterToken == null
                ? null
                : IconButton(
                    tooltip: '서버 접속 토큰 입력',
                    onPressed: onEnterToken,
                    icon: const Icon(Icons.key),
                  ),
          ),
        ),
      ],
    ),
  );
}
